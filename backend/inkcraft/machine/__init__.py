"""Machine adaptation: coordinate frames, port detection, GRBL settings, vendor imports."""

from inkcraft.machine.geometry import (
    check_machine_target,
    machine_bounds,
    machine_to_page,
    page_delta_to_machine,
    page_to_machine,
)
from inkcraft.machine.ports import annotate_ports, is_auto_port, pick_serial_port

__all__ = [
    "annotate_ports",
    "check_machine_target",
    "is_auto_port",
    "machine_bounds",
    "machine_to_page",
    "page_delta_to_machine",
    "page_to_machine",
    "pick_serial_port",
]
