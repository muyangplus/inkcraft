"""REST + WebSocket API package (Contract v1).

``create_app`` is resolved lazily so that importing ``inkcraft.api.schemas`` from
lower layers (gcode, machine, layout) does not pull in the whole web app.
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_app"]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from inkcraft.api.app import create_app

        return create_app
    raise AttributeError(name)
