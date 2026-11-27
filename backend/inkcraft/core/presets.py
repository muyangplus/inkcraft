"""File-backed layout preset store.

* ``config/presets/*.json``  — shipped presets (read-only, versioned in git)
* ``data/presets/*.json``    — user presets, e.g. imported from 奎享雕刻
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import threading

from inkcraft.api.schemas import LayoutPreset

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


class PresetStore:
    def __init__(self, builtin_dir: Path, user_dir: Path) -> None:
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir
        self._lock = threading.Lock()

    @staticmethod
    def _load_dir(d: Path) -> list[LayoutPreset]:
        out: list[LayoutPreset] = []
        if not d.is_dir():
            return out
        for p in sorted(d.glob("*.json")):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                items = raw if isinstance(raw, list) else [raw]
                out.extend(LayoutPreset.model_validate(it) for it in items)
            except Exception as exc:  # corrupt file must not break the API
                logger.warning("Skipping invalid preset file %s: %s", p, exc)
        return out

    def list(self) -> list[LayoutPreset]:
        seen: dict[str, LayoutPreset] = {}
        for preset in self._load_dir(self.builtin_dir) + self._load_dir(self.user_dir):
            seen[preset.preset_id] = preset  # user presets override shipped ones
        return list(seen.values())

    def save(self, preset: LayoutPreset) -> LayoutPreset:
        if not _SAFE.match(preset.preset_id):
            raise ValueError(f"非法 preset_id: {preset.preset_id!r}")
        with self._lock:
            self.user_dir.mkdir(parents=True, exist_ok=True)
            path = self.user_dir / f"{preset.preset_id}.json"
            path.write_text(preset.model_dump_json(indent=2), encoding="utf-8")
        return preset

    def delete(self, preset_id: str) -> bool:
        if not _SAFE.match(preset_id):
            return False
        path = self.user_dir / f"{preset_id}.json"
        with self._lock:
            if path.is_file():
                path.unlink()
                return True
        return False
