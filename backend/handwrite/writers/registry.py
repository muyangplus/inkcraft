"""Hot-swappable .hwfont writer registry with optional watchdog filesystem monitoring."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import threading
from typing import Callable

from hwfont_sdk import HwFontMeta, HwFontReader

logger = logging.getLogger(__name__)


class WriterRegistry:
    """Manages loaded .hwfont writers, active writer hot-swap, import, and deletion."""

    def __init__(
        self,
        fonts_dir: Path,
        *,
        on_change: Callable[[str | None], None] | None = None,
    ) -> None:
        self.fonts_dir = Path(fonts_dir).resolve()
        self.fonts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._readers: dict[str, HwFontReader] = {}
        self._active_writer_id: str | None = None
        self._on_change = on_change
        self._observer = None
        self.rescan()

    def rescan(self) -> list[HwFontMeta]:
        """Scan fonts_dir for valid .hwfont files, adding new ones and pruning removed ones."""
        with self._lock:
            existing_paths = {p.resolve() for p in self.fonts_dir.glob("*.hwfont") if p.is_file()}
            # Close readers whose backing file disappeared
            for wid, reader in list(self._readers.items()):
                if reader.path not in existing_paths:
                    reader.close()
                    del self._readers[wid]

            loaded_paths = {r.path for r in self._readers.values()}
            for path in sorted(existing_paths):
                if path in loaded_paths:
                    continue
                try:
                    reader = HwFontReader(path)
                    wid = reader.meta.writer_id
                    if wid in self._readers:
                        self._readers[wid].close()
                    self._readers[wid] = reader
                except Exception as exc:
                    logger.warning("Skipping invalid .hwfont file %s: %s", path.name, exc)

            if self._active_writer_id not in self._readers:
                user_wids = [
                    wid
                    for wid, r in self._readers.items()
                    if "generate_demo_writers" not in (r.meta.builder or "")
                ]
                self._active_writer_id = (
                    user_wids[0] if user_wids else next(iter(self._readers.keys()), None)
                )

            return [r.meta for r in self._readers.values()]

    def start_watching(self) -> None:
        """Start optional watchdog filesystem observer for hot-plugging .hwfont files."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return

        registry = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:  # type: ignore[override]
                src = getattr(event, "src_path", "")
                if str(src).endswith(".hwfont"):
                    registry.rescan()

        obs = Observer()
        obs.schedule(_Handler(), str(self.fonts_dir), recursive=False)
        obs.daemon = True
        obs.start()
        self._observer = obs

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None

    @property
    def active_writer_id(self) -> str | None:
        with self._lock:
            return self._active_writer_id

    def list_writers(self) -> list[HwFontMeta]:
        with self._lock:
            return [r.meta for r in self._readers.values()]

    def get(self, writer_id: str | None = None) -> HwFontReader | None:
        with self._lock:
            wid = writer_id or self._active_writer_id
            if wid is None:
                return None
            return self._readers.get(wid)

    def set_active(self, writer_id: str) -> HwFontMeta:
        with self._lock:
            if writer_id not in self._readers:
                raise KeyError(f"Writer not found: {writer_id}")
            self._active_writer_id = writer_id
            meta = self._readers[writer_id].meta
        if self._on_change is not None:
            self._on_change(writer_id)
        return meta

    def import_file(self, temp_path: Path, filename: str) -> HwFontMeta:
        """Validate, copy into fonts_dir, and load a newly uploaded .hwfont file."""
        safe_name = Path(filename).name
        if not safe_name.endswith(".hwfont"):
            safe_name = f"{safe_name}.hwfont"

        # Validate first before copying into fonts_dir
        with HwFontReader(temp_path) as probe:
            report = probe.verify()
            if not report.ok:
                raise ValueError(f"Invalid .hwfont file: {'; '.join(report.errors)}")
            wid = probe.meta.writer_id

        dest = self.fonts_dir / safe_name
        with self._lock:
            # Close existing reader if overwriting same writer_id or filename
            if wid in self._readers:
                old = self._readers.pop(wid)
                old.close()
            for k, r in list(self._readers.items()):
                if r.path == dest.resolve():
                    r.close()
                    del self._readers[k]

            shutil.copy2(temp_path, dest)
            reader = HwFontReader(dest)
            self._readers[reader.meta.writer_id] = reader
            if self._active_writer_id is None:
                self._active_writer_id = reader.meta.writer_id
            return reader.meta

    def delete(self, writer_id: str, *, protected_ids: set[str] | None = None) -> bool:
        with self._lock:
            if writer_id not in self._readers:
                raise KeyError(f"Writer not found: {writer_id}")
            if writer_id == self._active_writer_id or (
                protected_ids and writer_id in protected_ids
            ):
                raise PermissionError("Cannot delete active or in-use writer")
            reader = self._readers.pop(writer_id)
            path = reader.path
            reader.close()
            if path.exists():
                path.unlink()
            return True

    def close(self) -> None:
        self.stop_watching()
        with self._lock:
            for r in self._readers.values():
                r.close()
            self._readers.clear()
