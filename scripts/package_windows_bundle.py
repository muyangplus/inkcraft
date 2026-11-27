#!/usr/bin/env python3
"""Package a clean, portable Windows release bundle (`dist/inkcraft-windows-portable.zip`)."""

from __future__ import annotations

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT_ZIP = ROOT / "dist" / "inkcraft-windows-portable.zip"

EXCLUDE_TOP_LEVEL_DIRS = {
    "data",
    "dist",
    "source",
    "cuda_font_kit",
    "runtime",
}
EXCLUDE_ANYWHERE_DIRS = {
    ".venv",
    ".venv-cuda",
    ".venv-mineru",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log"}


def should_include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if rel.parts and rel.parts[0] in EXCLUDE_TOP_LEVEL_DIRS:
        return False
    for part in rel.parts:
        if part in EXCLUDE_ANYWHERE_DIRS:
            return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    return True


def build_bundle() -> Path:
    dist_index = ROOT / "frontend" / "dist" / "index.html"
    if not dist_index.is_file():
        raise FileNotFoundError("frontend/dist/index.html missing; run `npm --prefix frontend run build` first.")

    OUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()

    count = 0
    wrote_dist_index = False
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in sorted(ROOT.rglob("*")):
            if not file_path.is_file():
                continue
            if not should_include(file_path):
                continue
            rel = file_path.relative_to(ROOT)
            arcname = f"inkcraft-windows/{rel.as_posix()}"
            zf.write(file_path, arcname)
            if arcname == "inkcraft-windows/frontend/dist/index.html":
                wrote_dist_index = True
            count += 1

    if not wrote_dist_index:
        raise RuntimeError("Packaged Windows bundle is missing frontend/dist/index.html")

    size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"[OK] Packaged {count} files -> {OUT_ZIP} ({size_mb:.2f} MB)")
    return OUT_ZIP


if __name__ == "__main__":
    build_bundle()
