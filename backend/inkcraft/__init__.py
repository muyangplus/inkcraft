"""InkCraft (墨迹工坊): handwriting layout & GRBL pen-plotter host system."""

from __future__ import annotations

import os

__version__ = "2.0.0"
CONTRACT_VERSION = 1

_LEGACY_ENV_PREFIX = "HANDWRITE_"
_ENV_PREFIX = "INKCRAFT_"


def apply_legacy_env_aliases() -> None:
    """Map legacy ``HANDWRITE_*`` variables onto ``INKCRAFT_*`` (new names win)."""
    for key, val in list(os.environ.items()):
        if key.startswith(_LEGACY_ENV_PREFIX):
            new_key = _ENV_PREFIX + key[len(_LEGACY_ENV_PREFIX):]
            os.environ.setdefault(new_key, val)


apply_legacy_env_aliases()
