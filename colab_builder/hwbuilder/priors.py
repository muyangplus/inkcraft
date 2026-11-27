"""Cached built-in Hershey and MakeMeAHanzi stroke priors loaders."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import numpy as np


@lru_cache(maxsize=1)
def _load_builtin_priors_cached() -> dict[str, tuple[np.ndarray, ...]]:
    BUILTIN_GLYPHS = None
    for mod_name in ("hwbuilder.hershey_fallback", "handwrite.writers.fallback.hershey"):
        try:
            mod = __import__(mod_name, fromlist=["BUILTIN_GLYPHS"])
            BUILTIN_GLYPHS = getattr(mod, "BUILTIN_GLYPHS", None)
            if BUILTIN_GLYPHS:
                break
        except Exception:
            continue
    if not BUILTIN_GLYPHS:
        return {}

    priors: dict[str, tuple[np.ndarray, ...]] = {}
    for ch, (_adv, raw_strokes) in BUILTIN_GLYPHS.items():
        if not ch or ch.isspace():
            continue
        arrs = tuple(np.asarray(st, dtype=np.float64) for st in raw_strokes if len(st) >= 2)
        if arrs:
            for a in arrs:
                a.setflags(write=False)
            priors[ch] = arrs
    return priors


def load_builtin_priors() -> dict[str, list[np.ndarray]]:
    """Load built-in single-line priors from bundled `hwbuilder.hershey_fallback` or repo backend."""
    cached = _load_builtin_priors_cached()
    return {ch: [arr.copy() for arr in arrs] for ch, arrs in cached.items()}


def load_makemeahanzi_priors(graphics_jsonl_path: str | Path) -> dict[str, list[np.ndarray]]:
    """Load MakeMeAHanzi `graphics.txt` (JSONL with `character` & `medians`) into 0..1000 priors."""
    priors: dict[str, list[np.ndarray]] = {}
    p = Path(graphics_jsonl_path)
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            ch = obj.get("character")
            medians = obj.get("medians")
            if not ch or not medians:
                continue
            strokes: list[np.ndarray] = []
            for med in medians:
                if len(med) < 2:
                    continue
                arr = np.asarray(med, dtype=np.float64)
                arr[:, 0] = np.clip(arr[:, 0] * (1000.0 / 1024.0), 0.0, 1000.0)
                arr[:, 1] = np.clip((900.0 - arr[:, 1]) * (1000.0 / 1024.0), 0.0, 1000.0)
                strokes.append(arr)
            if strokes:
                priors[ch] = strokes
    return priors
