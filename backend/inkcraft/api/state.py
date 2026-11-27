"""Shared FastAPI application state container and unified API error type."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any

from inkcraft.api.schemas import (
    ComposedPage,
    LayoutConfig,
    LayoutPageSummary,
    MachineProfile,
)
from inkcraft.config import Settings
from inkcraft.core.db import Database
from inkcraft.core.events import EventBus
from inkcraft.core.presets import PresetStore
from inkcraft.core.tasks import TaskManager
from inkcraft.docparse.docir import DocIR
from inkcraft.gcode.compiler import CompiledGcode, compile_page_gcode
from inkcraft.gcode.optimizer import optimize_page
from inkcraft.grbl.controller import MachineController
from inkcraft.writers.registry import WriterRegistry

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def validate_safe_id(raw: str, label: str = "id") -> str:
    """Validate path-segment identifiers against traversal and malformed characters."""
    if not raw or ".." in raw or not _SAFE_ID_RE.fullmatch(raw):
        raise ApiError(400, "INVALID_ID", f"非法的 {label}: {raw}")
    return raw


class ApiError(Exception):
    """Structured API error rendered into Contract v1 error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class AppContext:
    """Lifecycle-managed singleton services attached to `app.state.ctx`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.event_bus = EventBus()
        self.db = Database(settings.DB_PATH, settings.PROFILES_PATH)
        self.tasks = TaskManager(self.db, self.event_bus)
        self.presets = PresetStore(
            settings.ROOT_DIR / "config" / "presets",
            settings.DATA_DIR / "presets",
        )
        self.writers = WriterRegistry(
            settings.FONTS_DIR,
            on_change=self._on_writer_changed,
        )
        self.machine = MachineController(
            self.event_bus,
            self.db,
            mock_speed_multiplier=settings.mock_speed_multiplier,
        )

    def _on_writer_changed(self, writer_id: str | None) -> None:
        if writer_id:
            self.event_bus.publish("writer.changed", {"writer_id": writer_id})

    def startup(self) -> None:
        self.writers.start_watching()
        self.seed_demo_document()

    def shutdown(self) -> None:
        try:
            self.machine.disconnect()
        except Exception:
            pass
        try:
            self.tasks.shutdown()
        except Exception:
            pass
        try:
            self.writers.close()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Document Storage Helpers
    # ------------------------------------------------------------------

    def doc_dir(self, doc_id: str) -> Path:
        safe_id = validate_safe_id(doc_id, "doc_id")
        base = self.settings.documents_dir.resolve()
        target = (base / safe_id).resolve()
        if not target.is_relative_to(base):
            raise ApiError(400, "INVALID_ID", f"非法的 doc_id 路径: {doc_id}")
        return target

    def save_docir(self, doc: DocIR, *, status: str = "ready") -> None:
        ddir = self.doc_dir(doc.doc_id)
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / "docir.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
        pages_meta: list[dict[str, Any]] = []
        for p in doc.pages:
            entry: dict[str, Any] = {
                "page_index": p.page_index,
                "width_mm": p.width_mm,
                "height_mm": p.height_mm,
            }
            if p.image is not None:
                entry["image"] = p.image
            pages_meta.append(entry)
        self.db.upsert_document(
            doc_id=doc.doc_id,
            filename=doc.source.filename,
            file_type=doc.source.type,
            sha256=doc.source.sha256,
            page_count=len(doc.pages),
            status=status,
            meta={
                "source": doc.source.model_dump(),
                "pages": pages_meta,
            },
        )

    def load_docir(self, doc_id: str) -> DocIR | None:
        path = self.doc_dir(doc_id) / "docir.json"
        if not path.is_file():
            return None
        return DocIR.model_validate_json(path.read_text(encoding="utf-8"))

    def seed_demo_document(self) -> None:
        """Auto-seed the built-in 2-page rich demo document `doc_demo` if missing."""
        demo_id = "doc_demo"
        if (self.doc_dir(demo_id) / "docir.json").is_file() and self.db.get_document(demo_id):
            return
        try:
            from inkcraft.docparse.service import build_demo_docir

            demo = build_demo_docir(demo_id)
            self.save_docir(demo, status="ready")
            logger.info("Seeded built-in demo document '%s' (%d pages)", demo_id, len(demo.pages))
        except Exception as exc:
            logger.warning("Could not seed demo document '%s': %s", demo_id, exc)

    # ------------------------------------------------------------------
    # Layout Storage & Compilation Helpers
    # ------------------------------------------------------------------

    def layout_dir(self, layout_id: str) -> Path:
        safe_id = validate_safe_id(layout_id, "layout_id")
        base = self.settings.layouts_dir.resolve()
        target = (base / safe_id).resolve()
        if not target.is_relative_to(base):
            raise ApiError(400, "INVALID_ID", f"非法的 layout_id 路径: {layout_id}")
        return target

    @staticmethod
    def compute_layout_cache_key(
        doc_id: str,
        doc_sha: str,
        writer_id: str,
        writer_sha: str,
        config: LayoutConfig,
        extra_writer_shas: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "doc_id": doc_id,
            "doc_sha": doc_sha,
            "writer_id": writer_id,
            "writer_sha": writer_sha,
            "config": config.model_dump(mode="json"),
        }
        if extra_writer_shas:
            payload["extra_writer_shas"] = dict(sorted(extra_writer_shas.items()))
        raw = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def save_layout_pages(
        self,
        *,
        layout_id: str,
        doc_id: str,
        writer_id: str,
        cache_key: str,
        config: LayoutConfig,
        pages: list[ComposedPage],
    ) -> dict[str, Any]:
        from inkcraft.layout.export import export_page_f32, export_page_json

        ldir = self.layout_dir(layout_id)
        pdir = ldir / "pages"
        pdir.mkdir(parents=True, exist_ok=True)

        summaries: list[dict[str, Any]] = []
        optimized_pages: list[ComposedPage] = []

        for page in pages:
            opt_page = optimize_page(page, config.optimize)
            optimized_pages.append(opt_page)

            idx = opt_page.page_index
            # 1. Full ComposedPage model for G-code compilation & framing
            (pdir / f"{idx}.page.json").write_text(
                opt_page.model_dump_json(), encoding="utf-8"
            )
            # 2. Contract v1 paths JSON
            exported_json = export_page_json(layout_id, opt_page)
            (pdir / f"{idx}.json").write_text(
                json.dumps(exported_json, ensure_ascii=False), encoding="utf-8"
            )
            # 3. Contract v1 binary Float32 path buffer + headers
            f32_bytes, f32_headers = export_page_f32(opt_page)
            (pdir / f"{idx}.f32").write_bytes(f32_bytes)
            (pdir / f"{idx}.f32.headers.json").write_text(
                json.dumps(f32_headers, ensure_ascii=False), encoding="utf-8"
            )

            summaries.append(
                LayoutPageSummary(
                    page_index=opt_page.page_index,
                    width_mm=opt_page.width_mm,
                    height_mm=opt_page.height_mm,
                    bbox=opt_page.bbox,
                    stats=opt_page.stats,
                    fallback_glyphs=opt_page.fallback_glyphs,
                    missing_glyphs=opt_page.missing_glyphs,
                    applied_rule_label=opt_page.applied_rule_label,
                    background_id=opt_page.background_id,
                    background_opacity=opt_page.background_opacity,
                    writer_id=opt_page.writer_id,
                    placed_blocks=opt_page.placed_blocks,
                ).model_dump()
            )

        config_dict = config.model_dump(mode="json")
        (ldir / "meta.json").write_text(
            json.dumps(
                {
                    "layout_id": layout_id,
                    "doc_id": doc_id,
                    "writer_id": writer_id,
                    "page_count": len(optimized_pages),
                    "config": config_dict,
                    "pages": summaries,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self.db.save_layout(
            layout_id=layout_id,
            doc_id=doc_id,
            writer_id=writer_id,
            cache_key=cache_key,
            config_dict=config_dict,
            page_count=len(optimized_pages),
            summary_pages=summaries,
        )
        return {
            "layout_id": layout_id,
            "doc_id": doc_id,
            "writer_id": writer_id,
            "page_count": len(optimized_pages),
            "config": config_dict,
            "pages": summaries,
        }

    def load_composed_page(self, layout_id: str, page_index: int) -> ComposedPage | None:
        path = self.layout_dir(layout_id) / "pages" / f"{page_index}.page.json"
        if not path.is_file():
            return None
        return ComposedPage.model_validate_json(path.read_text(encoding="utf-8"))

    def compile_layout_page(
        self,
        layout_id: str,
        page_index: int,
        profile: MachineProfile,
        *,
        validate_bounds: bool = True,
    ) -> CompiledGcode:
        page = self.load_composed_page(layout_id, page_index)
        if page is None:
            raise ApiError(
                404,
                "PAGE_NOT_FOUND",
                f"Layout '{layout_id}' page {page_index} not found",
            )
        compiled = compile_page_gcode(page, profile, validate_bounds=validate_bounds)
        pdir = self.layout_dir(layout_id) / "pages"
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / f"{page_index}.gcode").write_text(compiled.to_text(), encoding="utf-8")
        (pdir / f"{page_index}.lmap").write_text(
            json.dumps(
                {
                    "profile_id": profile.profile_id,
                    "line_to_stroke": compiled.line_to_stroke,
                    "stroke_to_line": compiled.stroke_to_line,
                    "est_s": compiled.est_s,
                    "draw_mm": compiled.draw_mm,
                    "travel_mm": compiled.travel_mm,
                }
            ),
            encoding="utf-8",
        )
        return compiled

    def get_active_profile(self) -> MachineProfile:
        active_id, profiles = self.db.list_profiles()
        if active_id:
            for p in profiles:
                if p.profile_id == active_id:
                    return p
        return profiles[0] if profiles else MachineProfile()
