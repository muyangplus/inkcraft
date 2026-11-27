#!/usr/bin/env python3
"""Export the FastAPI OpenAPI 3.1 JSON schema to `docs/openapi.json`.

Usage:
    python scripts/export_openapi.py
    python scripts/export_openapi.py --out docs/openapi.json --check
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for rel in ("packages/hwfont_sdk", "backend"):
    p = str(ROOT / rel)
    if p not in sys.path:
        sys.path.insert(0, p)


def export_openapi(out_path: Path, *, check: bool = False) -> int:
    from inkcraft.api.app import create_app  # type: ignore[import-not-found]

    app = create_app()
    schema = app.openapi()
    serialized = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"

    if check:
        if not out_path.exists():
            print(f"[FAIL] OpenAPI file does not exist: {out_path}", file=sys.stderr)
            return 1
        existing = out_path.read_text(encoding="utf-8")
        if existing != serialized:
            print(
                f"[FAIL] OpenAPI drift detected in {out_path}. "
                "Re-run `python scripts/export_openapi.py` to update.",
                file=sys.stderr,
            )
            return 1
        print(f"[OK] OpenAPI schema is up to date ({out_path}, openapi={schema.get('openapi')})")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(serialized, encoding="utf-8")
    paths_count = len(schema.get("paths", {}))
    print(
        f"[OK] Exported OpenAPI {schema.get('openapi', '3.1.0')} schema "
        f"({paths_count} paths) -> {out_path}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI 3.1 schema to JSON.")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "openapi.json",
        help="Destination JSON file path (default: docs/openapi.json).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the existing schema file matches without overwriting.",
    )
    args = parser.parse_args()
    return export_openapi(args.out, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
