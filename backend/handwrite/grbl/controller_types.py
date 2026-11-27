"""Shared state, error, and job context types for MachineController."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from handwrite.api.schemas import JobState, MachineProfile, MachineState, Vec3
from handwrite.gcode.compiler import CompiledGcode


class MachineStateError(RuntimeError):
    """Raised when an operation is disallowed in the current MachineState/JobState."""


@dataclass
class ActiveJobContext:
    """In-memory runtime state for the currently executing multi-page writing job."""

    job_id: str
    layout_id: str
    profile_id: str
    compiled_pages: dict[int, CompiledGcode]
    page_indices: list[int]
    current_pos_in_list: int = 0
    started_at: float = field(default_factory=time.monotonic)
    resume_line_idx: int = 0
    resume_stroke_idx: int = 0
    saved_wpos: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "z": 0.0})
    last_checkpoint_stroke: int = -1
    last_progress: dict[str, Any] = field(default_factory=dict)

    @property
    def current_page_index(self) -> int:
        return self.page_indices[self.current_pos_in_list]

    @property
    def current_compiled(self) -> CompiledGcode:
        return self.compiled_pages[self.current_page_index]


_ActiveJob = ActiveJobContext

__all__ = [
    "ActiveJobContext",
    "_ActiveJob",
    "JobState",
    "MachineProfile",
    "MachineState",
    "MachineStateError",
    "Vec3",
]
