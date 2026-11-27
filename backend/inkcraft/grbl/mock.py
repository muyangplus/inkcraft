"""Realistic MockGrblTransport simulating GRBL 1.1 kinematics, 128B RX & 15-slot planner."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
import threading
import time

from inkcraft.api.schemas import MachineProfile
from inkcraft.grbl.transport import SerialTransport

_WORD_RE = re.compile(r"([A-Za-z])([-+]?\d*\.?\d+)")


@dataclass
class _PlannerBlock:
    kind: str  # "move" | "jog" | "dwell" | "spindle" | "g92"
    target_mpos: tuple[float, float, float] | None = None
    feed_mm_min: float = 2400.0
    dwell_s: float = 0.0
    spindle: float | None = None
    g92_axes: dict[int, float] | None = None
    remaining_s: float = 0.0
    initialized: bool = False


class MockGrblTransport(SerialTransport):
    """In-process GRBL 1.1 hardware simulator for full-stack demos and automated tests."""

    def __init__(
        self,
        profile: MachineProfile | None = None,
        *,
        speed_multiplier: float = 10.0,
        planner_capacity: int = 15,
    ) -> None:
        super().__init__()
        self.profile = profile or MachineProfile()
        self.speed_multiplier = max(0.5, float(speed_multiplier))
        self.planner_capacity = max(4, int(planner_capacity))
        self.rx_buffer_size = int(self.profile.rx_buffer)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._open = False

        # Kinematics & GRBL modal state
        init_z = float(self.profile.pen.z_up_mm) if self.profile.pen.mode == "z" else 0.0
        self._mpos: list[float] = [0.0, 0.0, init_z]
        self._planned_mpos: list[float] = [0.0, 0.0, init_z]
        self._wco: list[float] = [0.0, 0.0, 0.0]
        self._grbl_state: str = "Idle"
        self._modal_motion: str = "G0"
        self._modal_distance: str = "G90"
        self._modal_feed: float = float(self.profile.feed_draw)
        self._spindle: float = 0.0
        self._current_feed: float = 0.0
        self._hold_decel_s: float = 0.0

        # Buffers
        self._rx_queue: deque[tuple[str, int]] = deque()
        self._rx_bytes: int = 0
        self._planner: deque[_PlannerBlock] = deque()
        self._active: _PlannerBlock | None = None
        self._peak_rx_bytes: int = 0

        # Persistent `$` settings (EEPROM); profile expectations override defaults
        self.settings: dict[int, float] = {
            0: 10.0, 1: 25.0, 2: 0.0, 3: 0.0, 10: 3.0, 13: 0.0, 20: 1.0, 22: 1.0,
            30: 1000.0, 31: 0.0, 32: 0.0,
            100: 250.0, 101: 250.0, 102: 250.0,  # GRBL 1.1 stock steps/mm
            120: 10.0, 121: 10.0, 122: 10.0,
            110: float(self.profile.feed_travel), 111: float(self.profile.feed_travel),
            112: float(self.profile.pen.z_feed),
            130: float(self.profile.workspace_mm.x), 131: float(self.profile.workspace_mm.y),
            132: 20.0,
        }
        for key, val in self.profile.grbl_expected.items():
            k = str(key).lstrip("$")
            if k.isdigit():
                self.settings[int(k)] = float(val)

    @property
    def peak_rx_bytes(self) -> int:
        with self._lock:
            return self._peak_rx_bytes

    def open(self) -> None:
        with self._lock:
            self._stop.clear()
            self._open = True
            self._grbl_state = "Idle"
            self._rx_queue.clear()
            self._rx_bytes = 0
            self._planner.clear()
            self._active = None
            self._spindle = 0.0
            self._current_feed = 0.0
            self._planned_mpos = list(self._mpos)

        self._thread = threading.Thread(
            target=self._sim_loop, name="mock-grbl-sim", daemon=True
        )
        self._thread.start()
        self._emit("Grbl 1.1h ['$' for help] (MockGRBL)")

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._open = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def is_open(self) -> bool:
        with self._lock:
            return self._open and not self._stop.is_set()

    def clear_tx_queue(self) -> None:
        # Host-side unsent queue clear (no-op for direct in-process mock)
        pass

    def send_line(self, line: str) -> None:
        cleaned = line.strip()
        if not cleaned or not self.is_open():
            return
        if self._on_log is not None:
            self._on_log("tx", cleaned)

        nbytes = len(cleaned.encode("ascii", errors="ignore")) + 1
        overflow = False
        with self._lock:
            if self._rx_bytes + nbytes > self.rx_buffer_size:
                overflow = True
            else:
                self._rx_queue.append((cleaned, nbytes))
                self._rx_bytes += nbytes
                if self._rx_bytes > self._peak_rx_bytes:
                    self._peak_rx_bytes = self._rx_bytes

        if overflow:
            self._emit("error:14")
        else:
            # Try immediate drain so interactive commands feel snappy
            self._drain_rx_to_planner()

    def send_realtime(self, cmd: bytes) -> None:
        if not cmd or not self.is_open():
            return
        b = cmd[:1]
        if self._on_log is not None and b != b"?":
            label = f"0x{b[0]:02x}" if b[0] < 32 or b[0] >= 127 else b.decode("ascii", "ignore")
            self._on_log("tx", label)

        if b == b"?":
            self._emit(self._format_status(), log_rx=False)
            return

        if b == b"\x18":
            # Soft reset: immediate halt, clear RX & planner, fail-safe servo M5, Alarm state
            with self._lock:
                self._rx_queue.clear()
                self._rx_bytes = 0
                self._planner.clear()
                self._active = None
                self._spindle = 0.0
                self._current_feed = 0.0
                self._hold_decel_s = 0.0
                self._planned_mpos = list(self._mpos)
                self._grbl_state = "Alarm"
            self._emit("Grbl 1.1h ['$' for help]")
            return

        if b == b"!":
            with self._lock:
                if self._grbl_state in ("Run", "Jog"):
                    self._grbl_state = "Hold:1"
                    self._hold_decel_s = 0.025
                elif self._grbl_state == "Idle":
                    self._grbl_state = "Hold:0"
            return

        if b == b"~":
            with self._lock:
                if self._grbl_state in ("Hold:0", "Hold:1"):
                    self._hold_decel_s = 0.0
                    if self._active is not None or self._planner:
                        self._grbl_state = "Run"
                    else:
                        self._grbl_state = "Idle"
            return

        if b == b"\x85":
            # Jog cancel
            with self._lock:
                if self._grbl_state == "Jog":
                    self._active = None
                    self._planner = deque(blk for blk in self._planner if blk.kind != "jog")
                    self._planned_mpos = list(self._mpos)
                    self._current_feed = 0.0
                    self._grbl_state = "Idle"
            return

        if b == b"\x9e":
            with self._lock:
                self._spindle = 0.0
            return

    # ------------------------------------------------------------------
    # Fault Injection Helpers (for tests / UI error scenarios)
    # ------------------------------------------------------------------

    def inject_alarm(self, code: int = 2) -> None:
        with self._lock:
            self._rx_queue.clear()
            self._rx_bytes = 0
            self._planner.clear()
            self._active = None
            self._spindle = 0.0
            self._current_feed = 0.0
            self._planned_mpos = list(self._mpos)
            self._grbl_state = "Alarm"
        self._emit(f"ALARM:{code}")

    def inject_error(self, code: int = 20) -> None:
        self._emit(f"error:{code}")

    def inject_disconnect(self, reason: str = "Simulated USB disconnect") -> None:
        self._stop.set()
        with self._lock:
            self._open = False
        if self._on_disconnect is not None:
            self._on_disconnect(reason)

    # ------------------------------------------------------------------
    # Internal Simulation Engine
    # ------------------------------------------------------------------

    def _emit(self, line: str, *, log_rx: bool = True) -> None:
        if log_rx and self._on_log is not None:
            self._on_log("rx", line)
        if self._on_line is not None:
            try:
                self._on_line(line)
            except Exception:
                pass

    def _format_status(self) -> str:
        with self._lock:
            k = (1.0 / 25.4) if int(self.settings.get(13, 0)) == 1 else 1.0
            mx, my, mz = (v * k for v in self._mpos)
            wcx, wcy, wcz = (v * k for v in self._wco)
            planner_avail = max(0, self.planner_capacity - len(self._planner) - (1 if self._active else 0))
            rx_avail = max(0, self.rx_buffer_size - self._rx_bytes)
            return (
                f"<{self._grbl_state}|"
                f"MPos:{mx:.3f},{my:.3f},{mz:.3f}|"
                f"WCO:{wcx:.3f},{wcy:.3f},{wcz:.3f}|"
                f"Bf:{planner_avail},{rx_avail}|"
                f"FS:{self._current_feed:.0f},{self._spindle:.0f}>"
            )

    def _drain_rx_to_planner(self) -> None:
        responses: list[str] = []
        with self._lock:
            while self._rx_queue:
                cmd, nbytes = self._rx_queue[0]
                upper = cmd.upper()

                # System commands handled immediately regardless of planner
                if upper == "$X":
                    self._rx_queue.popleft()
                    self._rx_bytes = max(0, self._rx_bytes - nbytes)
                    if self._grbl_state == "Alarm":
                        self._grbl_state = "Idle"
                    responses.append("[MSG:Caution: Unlocked]")
                    responses.append("ok")
                    continue

                if upper == "$H":
                    self._rx_queue.popleft()
                    self._rx_bytes = max(0, self._rx_bytes - nbytes)
                    init_z = float(self.profile.pen.z_up_mm) if self.profile.pen.mode == "z" else 0.0
                    self._mpos = [0.0, 0.0, init_z]
                    self._planned_mpos = list(self._mpos)
                    self._wco = [0.0, 0.0, 0.0]
                    self._spindle = 0.0
                    self._current_feed = 0.0
                    self._grbl_state = "Idle"
                    responses.append("ok")
                    continue

                if upper == "$$":
                    self._rx_queue.popleft()
                    self._rx_bytes = max(0, self._rx_bytes - nbytes)
                    responses.extend(f"${k}={v:g}" for k, v in sorted(self.settings.items()))
                    responses.append("ok")
                    continue

                if upper == "$#":
                    self._rx_queue.popleft()
                    self._rx_bytes = max(0, self._rx_bytes - nbytes)
                    responses.append(
                        f"[G92:{self._wco[0]:.3f},{self._wco[1]:.3f},{self._wco[2]:.3f}]"
                    )
                    responses.append("ok")
                    continue

                if upper.startswith("$") and not upper.startswith("$J="):
                    self._rx_queue.popleft()
                    self._rx_bytes = max(0, self._rx_bytes - nbytes)
                    key, sep, val = upper[1:].partition("=")
                    if sep and key.isdigit():
                        try:
                            self.settings[int(key)] = float(val)
                        except ValueError:
                            responses.append("error:3")
                            continue
                    elif upper == "$SLP":
                        self._grbl_state = "Sleep"
                    responses.append("ok")
                    continue

                if self._grbl_state == "Alarm":
                    self._rx_queue.popleft()
                    self._rx_bytes = max(0, self._rx_bytes - nbytes)
                    responses.append("error:9")
                    continue

                if self._grbl_state in ("Hold:0", "Hold:1"):
                    break

                if len(self._planner) >= self.planner_capacity:
                    break

                self._rx_queue.popleft()
                self._rx_bytes = max(0, self._rx_bytes - nbytes)
                resp = self._parse_and_enqueue(upper)
                responses.append(resp)

        for r in responses:
            self._emit(r)

    def _parse_and_enqueue(self, cmd: str) -> str:
        # Must be called under self._lock
        if cmd.startswith("$J="):
            body = cmd[3:]
            words = [(k.upper(), float(v)) for k, v in _WORD_RE.findall(body)]
            dist_mode = self._modal_distance
            feed = float(self.profile.jog_feed)
            dx, dy, dz = 0.0, 0.0, 0.0
            has_x = has_y = has_z = False
            tx, ty, tz = self._planned_mpos
            for letter, val in words:
                if letter == "G":
                    if int(val) == 90:
                        dist_mode = "G90"
                    elif int(val) == 91:
                        dist_mode = "G91"
                elif letter == "F":
                    feed = max(10.0, val)
                elif letter == "X":
                    dx = val
                    has_x = True
                elif letter == "Y":
                    dy = val
                    has_y = True
                elif letter == "Z":
                    dz = val
                    has_z = True

            if dist_mode == "G91":
                if has_x:
                    tx += dx
                if has_y:
                    ty += dy
                if has_z:
                    tz += dz
            else:
                if has_x:
                    tx = dx + self._wco[0]
                if has_y:
                    ty = dy + self._wco[1]
                if has_z:
                    tz = dz + self._wco[2]

            self._planned_mpos = [tx, ty, tz]
            self._planner.append(
                _PlannerBlock(kind="jog", target_mpos=(tx, ty, tz), feed_mm_min=feed)
            )
            self._grbl_state = "Jog"
            return "ok"

        words = [(k.upper(), float(v)) for k, v in _WORD_RE.findall(cmd)]
        if not words:
            return "ok"

        g_codes = [int(round(v)) for k, v in words if k == "G"]
        m_codes = [int(round(v)) for k, v in words if k == "M"]
        params: dict[str, float] = {}
        for k, v in words:
            if k not in ("G", "M"):
                params[k] = v

        # Handle M3 / M5 spindle (servo pen)
        if 5 in m_codes:
            self._planner.append(_PlannerBlock(kind="spindle", spindle=0.0))
            if self._grbl_state == "Idle":
                self._grbl_state = "Run"
            return "ok"
        if 3 in m_codes or 4 in m_codes:
            s_val = params.get("S", 90.0)
            self._planner.append(_PlannerBlock(kind="spindle", spindle=s_val))
            if self._grbl_state == "Idle":
                self._grbl_state = "Run"
            return "ok"

        # Handle G4 dwell
        if 4 in g_codes:
            p_sec = max(0.0, params.get("P", 0.0))
            self._planner.append(_PlannerBlock(kind="dwell", dwell_s=p_sec))
            if self._grbl_state == "Idle":
                self._grbl_state = "Run"
            return "ok"

        # Handle G92 coordinate offset
        if 92 in g_codes:
            axes: dict[int, float] = {}
            if "X" in params:
                axes[0] = params["X"]
            if "Y" in params:
                axes[1] = params["Y"]
            if "Z" in params:
                axes[2] = params["Z"]
            self._planner.append(_PlannerBlock(kind="g92", g92_axes=axes))
            if self._grbl_state == "Idle":
                self._grbl_state = "Run"
            return "ok"

        # Modal updates
        if 90 in g_codes:
            self._modal_distance = "G90"
        if 91 in g_codes:
            self._modal_distance = "G91"
        if 0 in g_codes:
            self._modal_motion = "G0"
        elif 1 in g_codes:
            self._modal_motion = "G1"

        if "F" in params:
            self._modal_feed = max(10.0, params["F"])

        has_axis = any(a in params for a in ("X", "Y", "Z"))
        if has_axis:
            tx, ty, tz = self._planned_mpos
            if self._modal_distance == "G91":
                if "X" in params:
                    tx += params["X"]
                if "Y" in params:
                    ty += params["Y"]
                if "Z" in params:
                    tz += params["Z"]
            else:
                if "X" in params:
                    tx = params["X"] + self._wco[0]
                if "Y" in params:
                    ty = params["Y"] + self._wco[1]
                if "Z" in params:
                    tz = params["Z"] + self._wco[2]

            feed = (
                float(self.profile.feed_travel)
                if self._modal_motion == "G0"
                else self._modal_feed
            )
            self._planned_mpos = [tx, ty, tz]
            self._planner.append(
                _PlannerBlock(kind="move", target_mpos=(tx, ty, tz), feed_mm_min=feed)
            )
            self._grbl_state = "Run"

        return "ok"

    def _sim_loop(self) -> None:
        tick = 0.01
        while not self._stop.is_set():
            self._drain_rx_to_planner()
            self._step_kinematics(tick)
            self._drain_rx_to_planner()
            time.sleep(tick)

    def _step_kinematics(self, real_dt: float) -> None:
        with self._lock:
            if self._grbl_state == "Alarm" or self._grbl_state == "Hold:0":
                self._current_feed = 0.0
                return

            if self._grbl_state == "Hold:1":
                self._hold_decel_s -= real_dt
                if self._hold_decel_s <= 0.0:
                    self._hold_decel_s = 0.0
                    self._grbl_state = "Hold:0"
                    self._current_feed = 0.0
                return

            budget_s = real_dt * self.speed_multiplier
            while budget_s > 1e-6:
                if self._active is None:
                    if not self._planner:
                        self._current_feed = 0.0
                        if self._grbl_state in ("Run", "Jog"):
                            self._grbl_state = "Idle"
                        break
                    self._active = self._planner.popleft()

                blk = self._active
                if blk.kind == "spindle":
                    self._spindle = float(blk.spindle or 0.0)
                    self._active = None
                    continue

                if blk.kind == "g92":
                    if blk.g92_axes:
                        for ax, target_w in blk.g92_axes.items():
                            self._wco[ax] = self._mpos[ax] - target_w
                    self._active = None
                    continue

                if blk.kind == "dwell":
                    if not blk.initialized:
                        blk.remaining_s = blk.dwell_s
                        blk.initialized = True
                    self._current_feed = 0.0
                    if blk.remaining_s <= budget_s:
                        budget_s -= blk.remaining_s
                        self._active = None
                    else:
                        blk.remaining_s -= budget_s
                        budget_s = 0.0
                    continue

                # Linear motion ("move" or "jog")
                assert blk.target_mpos is not None
                tx, ty, tz = blk.target_mpos
                dx = tx - self._mpos[0]
                dy = ty - self._mpos[1]
                dz = tz - self._mpos[2]
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist <= 1e-6:
                    self._mpos = [tx, ty, tz]
                    self._active = None
                    continue

                v_mm_s = max(1.0, blk.feed_mm_min / 60.0)
                self._current_feed = blk.feed_mm_min
                self._grbl_state = "Jog" if blk.kind == "jog" else "Run"
                needed_s = dist / v_mm_s
                if needed_s <= budget_s:
                    self._mpos = [tx, ty, tz]
                    budget_s -= needed_s
                    self._active = None
                else:
                    frac = budget_s / needed_s
                    self._mpos[0] += dx * frac
                    self._mpos[1] += dy * frac
                    self._mpos[2] += dz * frac
                    budget_s = 0.0

            if self._active is None and not self._planner and self._grbl_state in ("Run", "Jog"):
                self._grbl_state = "Idle"
                self._current_feed = 0.0
