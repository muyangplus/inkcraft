"""CLI entrypoint: `python -m inkcraft --host 127.0.0.1 --port 8765`."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from inkcraft import apply_legacy_env_aliases
from inkcraft.api.app import create_app
from inkcraft.config import Settings


def _load_dotenv(env_path: Path) -> None:
    """Load simple KEY=VALUE lines from `.env` if present (no third-party dependency)."""
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass
    apply_legacy_env_aliases()


def _find_available_port(host: str, start_port: int, max_tries: int = 32) -> int:
    for p in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return start_port


def _open_browser_later(url: str, delay_s: float = 1.4) -> None:
    def _worker() -> None:
        time.sleep(delay_s)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True, name="open-browser").start()


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    _load_dotenv(repo_root / ".env")

    parser = argparse.ArgumentParser(
        prog="inkcraft",
        description="Standalone AI Multi-Writer Handwriting & GRBL Writing Arm Host Server",
    )
    parser.add_argument("--host", default=os.environ.get("INKCRAFT_HOST", "127.0.0.1"), help="Bind host")
    parser.add_argument("--port", type=int, default=int(os.environ.get("INKCRAFT_PORT", "8765")), help="Bind port")
    parser.add_argument("--auto-port", action="store_true", help="Automatically pick next free port if busy")
    parser.add_argument("--open-browser", action="store_true", help="Open web workbench in default browser on startup")
    parser.add_argument("--fonts-dir", type=Path, default=None, help="Directory of .hwfont files")
    parser.add_argument("--data-dir", type=Path, default=None, help="Runtime data directory")
    parser.add_argument(
        "--mock-speed",
        type=float,
        default=float(os.environ.get("INKCRAFT_MOCK_SPEED", "10.0")),
        help="Mock GRBL speed multiplier (default: 10.0)",
    )
    parser.add_argument("--log-level", default="info", help="Uvicorn log level")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = _find_available_port(args.host, args.port) if args.auto_port else args.port
    if port != args.port:
        logging.getLogger(__name__).info("Port %d busy, switched automatically to %d", args.port, port)

    settings = Settings(
        host=args.host,
        port=port,
        fonts_dir=args.fonts_dir,
        data_dir=args.data_dir,
        mock_speed_multiplier=args.mock_speed,
    )
    app = create_app(settings)

    if args.open_browser:
        url = f"http://{settings.host}:{settings.port}"
        logging.getLogger(__name__).info("Opening browser at %s", url)
        _open_browser_later(url)

    uvicorn.run(app, host=settings.host, port=settings.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
