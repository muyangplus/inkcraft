"""System health and GPU availability endpoint."""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from fastapi import APIRouter

from handwrite import CONTRACT_VERSION, __version__

router = APIRouter()

_GPU_CACHE: tuple[float, dict[str, Any]] | None = None


def _probe_gpu() -> dict[str, Any]:
    global _GPU_CACHE
    now = time.monotonic()
    if _GPU_CACHE is not None and (now - _GPU_CACHE[0]) < 30.0:
        return _GPU_CACHE[1]

    info: dict[str, Any] = {"available": False, "name": None, "vram_free_mb": None}
    nvsmi = shutil.which("nvidia-smi")
    if nvsmi:
        try:
            proc = subprocess.run(
                [nvsmi, "--query-gpu=name,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                line = proc.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    info = {
                        "available": True,
                        "name": parts[0],
                        "vram_free_mb": int(float(parts[1])),
                    }
        except Exception:
            pass

    _GPU_CACHE = (now, info)
    return info


@router.get("/health")
async def get_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "contract_version": CONTRACT_VERSION,
        "gpu": _probe_gpu(),
    }
