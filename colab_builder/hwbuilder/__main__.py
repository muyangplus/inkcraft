"""Command-line interface for `hwbuilder` (`python -m hwbuilder capabilities|sheets|build`)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from hwbuilder.local_runner import (
    LocalBuildConfig,
    preset_charset,
    probe_capabilities,
    run_local_font_build,
)
from hwbuilder.sheet_gen import SheetConfig, generate_collection_sheets


def _cmd_capabilities(_args: argparse.Namespace) -> int:
    caps = probe_capabilities()
    print(json.dumps(caps, ensure_ascii=False, indent=2))
    return 0


def _cmd_sheets(args: argparse.Namespace) -> int:
    chars = preset_charset(args.preset, args.custom_chars)
    cfg = SheetConfig(
        writer_name=args.writer,
        rows=args.rows,
        cols=args.cols,
        grid_color=args.grid_color,
        preview_dpi=args.preview_dpi,
    )
    manifest = generate_collection_sheets(
        chars=chars,
        out_dir=args.out,
        config=cfg,
        render_previews=not args.no_previews,
    )
    print(
        json.dumps(
            {
                "writer_name": manifest.writer_name,
                "pages": len(manifest.pages),
                "chars": sum(len(p.cells) for p in manifest.pages),
                "pdf": str(Path(args.out) / manifest.pdf_path),
                "manifest": str(Path(args.out) / "manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    tags = [t.strip() for t in args.style_tags.replace("，", ",").split(",") if t.strip()]
    cfg = LocalBuildConfig(
        writer_name=args.writer_name,
        writer_alias=args.writer_alias,
        style_tags=tags,
        engine=args.engine,
        variants_per_char=args.variants,
        target_preset=args.preset,
        grid_color=args.grid_color,
        makemeahanzi_path=args.makemeahanzi,
    )

    def _progress(stage: str, pct: float, msg: str) -> None:
        print(f"[{pct:5.1f}%] ({stage}) {msg}", file=sys.stderr)

    res = run_local_font_build(
        out_hwfont=args.out,
        config=cfg,
        scan_paths=args.scans or (),
        manifest_path=args.manifest,
        demo_synthetic=args.demo_synthetic,
        work_dir=args.work_dir,
        progress=_progress,
    )
    print(
        json.dumps(
            {
                "ok": res.verify_report.ok,
                "out_hwfont": str(res.out_hwfont),
                "engine_used": res.engine_used,
                "glyph_count": res.glyph_count,
                "variant_count": res.variant_count,
                "scanned_glyphs_count": res.scanned_glyphs_count,
                "accepted_variants": res.accepted_variants,
                "rejected_variants": res.rejected_variants,
                "content_sha256": res.verify_report.actual_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if res.verify_report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hwbuilder",
        description="Local (GPU/CPU) & Colab offline-to-online .hwfont builder CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_cap = sub.add_parser("capabilities", help="Probe local CUDA GPU, PyTorch, and OpenCV status.")
    p_cap.set_defaults(func=_cmd_capabilities)

    p_sh = sub.add_parser("sheets", help="Generate printable A4 ArUco collection sheets + manifest.")
    p_sh.add_argument("--preset", choices=("quick", "standard", "custom"), default="standard")
    p_sh.add_argument("--custom-chars", default="", help="Characters when --preset=custom.")
    p_sh.add_argument("--writer", default="my_writer", help="Writer identifier shown on sheet header.")
    p_sh.add_argument("--grid-color", choices=("cyan", "red"), default="cyan")
    p_sh.add_argument("--rows", type=int, default=12)
    p_sh.add_argument("--cols", type=int, default=10)
    p_sh.add_argument("--preview-dpi", type=int, default=150)
    p_sh.add_argument("--no-previews", action="store_true")
    p_sh.add_argument("--out", type=Path, required=True, help="Output directory for PDF & manifest.")
    p_sh.set_defaults(func=_cmd_sheets)

    p_bld = sub.add_parser("build", help="Run local offline scan -> .hwfont build.")
    p_bld.add_argument("--writer-name", required=True, help="Display name of the writer.")
    p_bld.add_argument("--writer-alias", default="", help="Optional style alias.")
    p_bld.add_argument("--style-tags", default="", help="Comma-separated style tags.")
    p_bld.add_argument("--scans", nargs="*", type=Path, default=[], help="Scanned sheet PNG/JPG files.")
    p_bld.add_argument("--manifest", type=Path, default=None, help="Path to sheet manifest.json.")
    p_bld.add_argument("--demo-synthetic", action="store_true", help="Synthesize demo scans automatically.")
    p_bld.add_argument("--engine", choices=("auto", "local_gpu", "local_cpu"), default="auto")
    p_bld.add_argument("--variants", type=int, default=3, help="Target variants per character.")
    p_bld.add_argument("--preset", choices=("quick", "standard", "scanned_only"), default="standard")
    p_bld.add_argument("--grid-color", choices=("cyan", "red"), default="cyan")
    p_bld.add_argument("--makemeahanzi", type=Path, default=None, help="Optional graphics.txt priors path.")
    p_bld.add_argument("--work-dir", type=Path, default=None, help="Optional persistent scratch directory.")
    p_bld.add_argument("--out", type=Path, required=True, help="Output .hwfont file path.")
    p_bld.set_defaults(func=_cmd_build)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
