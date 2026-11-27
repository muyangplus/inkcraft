"""Deterministic hierarchical RNG, anthropomorphic glyph perturbation, and hand-drawn polylines."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from inkcraft.api.schemas import PerturbConfig


def _hash32(value: object) -> int:
    raw = str(value).encode("utf-8")
    digest = hashlib.blake2b(raw, digest_size=4).digest()
    return int.from_bytes(digest, "little", signed=False)


def scope_rng(seed: int, *scope: object) -> np.random.Generator:
    """Create a deterministic PCG64 Generator scoped to `(seed, *scope)`."""
    entropy = [int(seed) & 0xFFFFFFFF]
    for item in scope:
        if isinstance(item, int) and 0 <= item <= 0xFFFFFFFF:
            entropy.append(item)
        else:
            entropy.append(_hash32(item))
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))


@dataclass
class LineWaveState:
    """Line-scoped baseline wave (sin + AR1) and slant tone."""

    phase_rad: float
    period_mm: float
    amp_mm: float
    beta_slant_deg: float
    ar1: float = 0.0

    @classmethod
    def create(cls, cfg: PerturbConfig, rng: np.random.Generator) -> LineWaveState:
        phase = float(rng.uniform(0.0, 2.0 * math.pi))
        beta = float(cfg.slant_deg * rng.uniform(0.6, 1.0)) if cfg.slant_deg > 0 else 0.0
        return cls(
            phase_rad=phase,
            period_mm=max(20.0, float(cfg.baseline_wave_period_mm)),
            amp_mm=float(cfg.baseline_wave_amp_mm),
            beta_slant_deg=beta,
            ar1=0.0,
        )

    def sample_dy(self, x_mm: float, rng: np.random.Generator, mult: float = 1.0) -> float:
        amp = self.amp_mm * mult
        if amp <= 1e-6:
            return 0.0
        self.ar1 = 0.7 * self.ar1 + float(rng.normal(0.0, 0.15 * amp))
        self.ar1 = max(-amp, min(amp, self.ar1))
        wave = amp * math.sin((2.0 * math.pi * x_mm / self.period_mm) + self.phase_rad)
        total = wave + self.ar1
        return max(-amp, min(amp, total))


def neatness_factors(neatness: float) -> tuple[float, float]:
    """Return `(jitter_mult, cursive_strength)` from `neatness` in `[0.0, 1.0]`.

    - `neatness = 1.0` (一笔一画工整): `jitter_mult = 0.15`, `cursive_strength = 0.0` (no ligatures).
    - `neatness = 0.72` (默认自然行楷): `jitter_mult = 1.0`, `cursive_strength = 0.0`.
    - `neatness = 0.0` (连笔潦草): `jitter_mult = 2.15`, `cursive_strength = 1.0` (strong ligatures & fluidity).
    """
    n = max(0.0, min(1.0, float(neatness)))
    c = 1.0 - n
    if c <= 0.28:
        jitter_mult = 0.15 + 0.85 * (c / 0.28)
        cursive_strength = 0.0
    else:
        cursive_strength = (c - 0.28) / 0.72
        jitter_mult = 1.0 + 1.15 * cursive_strength
    return jitter_mult, cursive_strength


def _chaikin_smooth(pts: np.ndarray, iterations: int = 1) -> np.ndarray:
    """Endpoint-preserving Chaikin corner rounding for fluid cursive strokes."""
    arr = pts
    for _ in range(iterations):
        if len(arr) < 3:
            break
        q = 0.75 * arr[:-1] + 0.25 * arr[1:]
        r = 0.25 * arr[:-1] + 0.75 * arr[1:]
        mid = np.empty((2 * len(q), 2), dtype=np.float64)
        mid[0::2] = q
        mid[1::2] = r
        arr = np.vstack((arr[0:1], mid[1:-1], arr[-1:]))
    return arr


def _bezier_bridge(p0: np.ndarray, t0: np.ndarray, p1: np.ndarray, cursive_strength: float, rng: np.random.Generator) -> np.ndarray:
    """Create a smooth 4-point calligraphic ligature arc from `p0` to `p1`."""
    delta = p1 - p0
    dist = float(np.hypot(delta[0], delta[1]))
    if dist < 1e-4:
        return np.empty((0, 2), dtype=np.float64)
    # Control point follows exit tangent gently with slight organic bow
    normal = np.array([-delta[1], delta[0]], dtype=np.float64) / dist
    bow = float(rng.normal(0.0, 0.14 * dist * (0.5 + 0.5 * cursive_strength)))
    ctrl = 0.5 * (p0 + p1) + t0 * (dist * 0.22) + normal * bow
    ts = np.array([0.25, 0.5, 0.75], dtype=np.float64)[:, None]
    omt = 1.0 - ts
    return (omt * omt) * p0 + (2.0 * omt * ts) * ctrl + (ts * ts) * p1


def _apply_cursive_dynamics(
    strokes: list[np.ndarray],
    *,
    font_size_mm: float,
    cursive_strength: float,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    """Apply corner rounding, fluid stroke overshoot, and intra-glyph ligatures."""
    if not strokes or cursive_strength <= 0.02:
        return strokes

    chaikin_iters = 2 if cursive_strength > 0.62 else (1 if cursive_strength > 0.16 else 0)
    processed: list[np.ndarray] = []

    for st in strokes:
        arr = np.asarray(st, dtype=np.float64)
        if len(arr) < 2:
            continue

        # Subtle fluid endpoint overshoot along stroke tangent
        if len(arr) >= 2 and cursive_strength > 0.10:
            arr = arr.copy()
            d_start = arr[1] - arr[0]
            len_s = float(np.hypot(d_start[0], d_start[1]))
            if len_s > 0.12:
                ext_s = float(rng.uniform(-0.02, 0.07)) * font_size_mm * cursive_strength
                arr[0] = arr[0] - (d_start / len_s) * ext_s
            d_end = arr[-1] - arr[-2]
            len_e = float(np.hypot(d_end[0], d_end[1]))
            if len_e > 0.12:
                ext_e = float(rng.uniform(0.0, 0.11)) * font_size_mm * cursive_strength
                arr[-1] = arr[-1] + (d_end / len_e) * ext_e

        # Expressive wave drift on longer strokes at high cursiveness
        if len(arr) >= 3 and cursive_strength > 0.25:
            mid_drift = rng.normal(0.0, font_size_mm * 0.022 * cursive_strength, size=(len(arr) - 2, 2))
            arr[1:-1] = arr[1:-1] + mid_drift

        if chaikin_iters > 0 and len(arr) >= 3:
            arr = _chaikin_smooth(arr, iterations=chaikin_iters)
            arr = rdp_simplify(arr, max(0.03, font_size_mm * 0.008))

        processed.append(arr)

    if len(processed) <= 1 or cursive_strength < 0.06:
        return processed

    # Intra-glyph ligature bridging (字内连笔牵丝)
    max_jump = font_size_mm * (0.28 + 0.88 * cursive_strength)
    linked: list[np.ndarray] = [processed[0]]
    for nxt in processed[1:]:
        prev = linked[-1]
        p0 = prev[-1]
        p1 = nxt[0]
        dist = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        if dist <= max_jump:
            p_link = min(0.96, (0.18 + 0.82 * cursive_strength) * (1.0 - 0.42 * (dist / max(1e-4, max_jump))))
            if float(rng.random()) < p_link:
                d_prev = prev[-1] - prev[-2]
                norm_p = float(np.hypot(d_prev[0], d_prev[1]))
                t0 = (d_prev / norm_p) if norm_p > 1e-4 else np.zeros(2, dtype=np.float64)
                bridge = _bezier_bridge(p0, t0, p1, cursive_strength, rng)
                if len(bridge) > 0:
                    linked[-1] = np.vstack((prev, bridge, nxt))
                else:
                    linked[-1] = np.vstack((prev, nxt))
                continue
        linked.append(nxt)

    return linked


def connect_inter_glyph_strokes(
    glyph_stroke_groups: list[list[np.ndarray]],
    *,
    font_size_mm: float,
    neatness: float,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    """Optionally join consecutive glyphs on a line with light cursive ligatures at low neatness."""
    _, cursive_strength = neatness_factors(neatness)
    if not glyph_stroke_groups:
        return []
    if cursive_strength <= 0.50:
        return [st for grp in glyph_stroke_groups for st in grp]

    inter_strength = (cursive_strength - 0.50) / 0.50  # 0..1 when neatness in [0.0, 0.36)
    max_gap = font_size_mm * (0.26 + 0.58 * inter_strength)
    merged: list[np.ndarray] = []

    for grp in glyph_stroke_groups:
        if not grp:
            continue
        if merged:
            prev = merged[-1]
            first = grp[0]
            p0, p1 = prev[-1], first[0]
            dist = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
            # Only connect forward/nearby left-to-right strokes so writing never jumps backwards
            if dist <= max_gap and (p1[0] >= p0[0] - font_size_mm * 0.25):
                p_join = min(0.82, 0.15 + 0.65 * inter_strength) * (1.0 - 0.35 * (dist / max(1e-4, max_gap)))
                if float(rng.random()) < p_join:
                    d_prev = prev[-1] - prev[-2]
                    norm_p = float(np.hypot(d_prev[0], d_prev[1]))
                    t0 = (d_prev / norm_p) if norm_p > 1e-4 else np.zeros(2, dtype=np.float64)
                    bridge = _bezier_bridge(p0, t0, p1, inter_strength, rng)
                    merged[-1] = np.vstack((prev, bridge, first)) if len(bridge) > 0 else np.vstack((prev, first))
                    merged.extend(grp[1:])
                    continue
        merged.extend(grp)
    return merged


def sample_spacing_factor(cfg: PerturbConfig, rng: np.random.Generator, mult: float = 1.0) -> float:
    neat_mult, _ = neatness_factors(cfg.neatness)
    k = float(cfg.spacing_jitter) * mult * neat_mult
    if k <= 1e-6:
        return 1.0
    return 1.0 + float(rng.uniform(-k, k))


def transform_glyph_strokes(
    strokes: list[np.ndarray],
    *,
    origin_x_mm: float,
    baseline_y_mm: float,
    font_size_mm: float,
    units_per_em: float = 1000.0,
    baseline_u: float = 800.0,
    advance_u: float = 1000.0,
    cfg: PerturbConfig,
    rng: np.random.Generator,
    line_state: LineWaveState | None = None,
    scale_mult: float = 1.0,
    wave_mult: float = 1.0,
    slant_mult: float = 1.0,
    rot_mult: float = 1.0,
    extra_italic_deg: float = 0.0,
    allow_cursive: bool = True,
    char_scale_x: float = 1.0,
    char_scale_y: float = 1.0,
) -> list[np.ndarray]:
    """Map single-line glyph strokes from 0..1000 em space to page mm via one 3x3 affine matrix."""
    if not strokes:
        return []

    em_scale = float(font_size_mm) / max(1.0, float(units_per_em))
    neat_mult, cursive_strength = neatness_factors(cfg.neatness)

    # 1. Per-glyph scale jitter anchored at (advance/2, baseline_u)
    j = min(0.35, float(cfg.scale_jitter) * scale_mult * neat_mult)
    if j > 1e-6:
        s = 1.0 + float(np.clip(rng.normal(0.0, j * 0.5), -j, j))
    else:
        s = 1.0
    # Hurried cursive stretches slightly horizontally and compresses slightly vertically
    sx = s * float(char_scale_x) * (1.0 + (0.10 * cursive_strength if allow_cursive else 0.0))
    sy = s * float(char_scale_y) * (1.0 - (0.06 * cursive_strength if allow_cursive else 0.0))

    # 2. Slant (line tone + per-glyph variance + cursive forward lean + optional math italic)
    base_slant = line_state.beta_slant_deg if line_state is not None else float(cfg.slant_deg) * 0.8
    slant_sigma = 0.25 * float(cfg.slant_deg) * slant_mult * neat_mult
    cursive_lean = (8.0 * (cursive_strength ** 1.15)) if allow_cursive else 0.0
    theta_deg = (base_slant * slant_mult * min(1.5, neat_mult)) + cursive_lean + (
        float(rng.normal(0.0, slant_sigma)) if slant_sigma > 1e-6 else 0.0
    ) + float(extra_italic_deg)
    shear = math.tan(math.radians(theta_deg))

    # 3. Micro-rotation around glyph center
    rot_sigma = float(cfg.rotation_jitter_deg) * rot_mult * neat_mult
    rot_deg = float(np.clip(rng.normal(0.0, rot_sigma), -2.5 * rot_sigma, 2.5 * rot_sigma)) if rot_sigma > 1e-6 else 0.0
    rot_rad = math.radians(rot_deg)
    cos_r = math.cos(rot_rad)
    sin_r = math.sin(rot_rad)

    # 4. Baseline wave offset in mm
    dy_mm = line_state.sample_dy(origin_x_mm, rng, mult=wave_mult * neat_mult) if line_state is not None else 0.0

    # Compose transform in glyph units around anchor (ax, ay), then scale to mm & translate
    ax = 0.5 * float(advance_u)
    ay = float(baseline_u)
    cx = ax
    cy = 0.5 * float(baseline_u)

    # M_final maps [ux, uy, 1]^T -> [x_mm, y_mm, 1]^T
    # Step A: scale around (ax, ay)
    T_to_anchor = np.array([[1.0, 0.0, -ax], [0.0, 1.0, -ay], [0.0, 0.0, 1.0]], dtype=np.float64)
    S_mat = np.array([[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    # Step B: slant shear relative to baseline_y (y < baseline_u shifts +x -> natural right lean)
    Sh_mat = np.array([[1.0, -shear, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    T_from_anchor = np.array([[1.0, 0.0, ax], [0.0, 1.0, ay], [0.0, 0.0, 1.0]], dtype=np.float64)

    # Step C: rotation around glyph center (cx, cy)
    T_to_c = np.array([[1.0, 0.0, -cx], [0.0, 1.0, -cy], [0.0, 0.0, 1.0]], dtype=np.float64)
    R_mat = np.array([[cos_r, -sin_r, 0.0], [sin_r, cos_r, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    T_from_c = np.array([[1.0, 0.0, cx], [0.0, 1.0, cy], [0.0, 0.0, 1.0]], dtype=np.float64)

    # Step D: em -> mm with baseline_u mapped to baseline_y_mm + dy_mm
    To_mm = np.array(
        [
            [em_scale, 0.0, float(origin_x_mm)],
            [0.0, em_scale, float(baseline_y_mm) + dy_mm - ay * em_scale],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )

    M = To_mm @ T_from_c @ R_mat @ T_to_c @ T_from_anchor @ Sh_mat @ S_mat @ T_to_anchor
    A = M[:2, :2].T  # (2, 2) for row-vector multiplication
    t = M[:2, 2]  # (2,)

    out: list[np.ndarray] = []
    for st in strokes:
        arr = np.asarray(st, dtype=np.float64)
        if arr.ndim != 2 or len(arr) < 2:
            continue
        transformed = arr @ A + t
        out.append(transformed)

    if allow_cursive and cursive_strength > 0.02:
        out = _apply_cursive_dynamics(
            out,
            font_size_mm=font_size_mm,
            cursive_strength=cursive_strength,
            rng=rng,
        )
    return out


def rdp_simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Ramer-Douglas-Peucker polyline simplification for an `(N, 2)` float array."""
    arr = np.asarray(pts, dtype=np.float64)
    n = len(arr)
    if n <= 2 or tol <= 0.0:
        return arr

    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[-1] = True
    stack = [(0, n - 1)]
    tol_sq = tol * tol

    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        p0 = arr[i0]
        p1 = arr[i1]
        seg = p1 - p0
        seg_len_sq = float(seg[0] * seg[0] + seg[1] * seg[1])
        sub = arr[i0 + 1 : i1] - p0
        if seg_len_sq <= 1e-12:
            dist_sq = sub[:, 0] ** 2 + sub[:, 1] ** 2
        else:
            t = np.clip((sub[:, 0] * seg[0] + sub[:, 1] * seg[1]) / seg_len_sq, 0.0, 1.0)
            proj = np.column_stack((t * seg[0], t * seg[1]))
            diff = sub - proj
            dist_sq = diff[:, 0] ** 2 + diff[:, 1] ** 2
        rel_max = int(np.argmax(dist_sq))
        if float(dist_sq[rel_max]) > tol_sq:
            idx = i0 + 1 + rel_max
            keep[idx] = True
            stack.append((i0, idx))
            stack.append((idx, i1))

    return arr[keep]


def _resample_polyline(pts: np.ndarray, step_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """Resample a polyline at approximately uniform arc-length `step_mm`."""
    arr = np.asarray(pts, dtype=np.float64)
    if len(arr) < 2:
        return arr, np.zeros(len(arr), dtype=np.float64)
    diffs = np.diff(arr, axis=0)
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    total_len = float(np.sum(seg_lens))
    if total_len <= 1e-6:
        return arr[:2], np.array([0.0, 0.0], dtype=np.float64)

    cum = np.concatenate(([0.0], np.cumsum(seg_lens)))
    n_samples = max(2, int(math.ceil(total_len / max(0.25, step_mm))) + 1)
    # Cap sample count for huge shapes to stay fast
    n_samples = min(n_samples, 180)
    s_vals = np.linspace(0.0, total_len, n_samples)
    xs = np.interp(s_vals, cum, arr[:, 0])
    ys = np.interp(s_vals, cum, arr[:, 1])
    return np.column_stack((xs, ys)), s_vals


def _smooth_value_noise_1d(s_vals: np.ndarray, wavelength: float, rng: np.random.Generator) -> np.ndarray:
    """Seeded C1-smooth 1D value noise evaluated at arc-length coordinates `s_vals`."""
    if len(s_vals) == 0:
        return np.zeros(0, dtype=np.float64)
    phase = float(rng.uniform(0.0, 100.0))
    u = s_vals / max(1.0, wavelength) + phase
    u0 = int(math.floor(float(u[0])))
    u1 = int(math.ceil(float(u[-1]))) + 2
    knots = rng.uniform(-1.0, 1.0, size=max(4, u1 - u0 + 1))

    idx = np.floor(u).astype(np.int64) - u0
    idx = np.clip(idx, 0, len(knots) - 2)
    frac = u - np.floor(u)
    # Smoothstep 3t^2 - 2t^3
    smooth = frac * frac * (3.0 - 2.0 * frac)
    return knots[idx] * (1.0 - smooth) + knots[idx + 1] * smooth


def hand_draw_polyline(
    pts: np.ndarray,
    jitter_mm: float,
    rng: np.random.Generator,
    *,
    overshoot_mm: float = 0.25,
    resample_step_mm: float = 1.5,
    simplify_tol_mm: float = 0.06,
    closed: bool = False,
) -> np.ndarray:
    """Apply smooth hand-drawn perturbation (normal value noise + subtle bow + end overshoot)."""
    arr = np.asarray(pts, dtype=np.float64)
    if arr.ndim != 2 or len(arr) < 2:
        return arr
    if closed and len(arr) >= 3 and float(np.linalg.norm(arr[0] - arr[-1])) > 1e-6:
        arr = np.vstack([arr, arr[0:1]])
    if jitter_mm <= 1e-6 and overshoot_mm <= 1e-6:
        return arr.copy()

    resampled, s_vals = _resample_polyline(arr, resample_step_mm)
    total_len = float(s_vals[-1]) if len(s_vals) > 0 else 0.0
    if total_len <= 0.15 or len(resampled) < 2:
        return arr.copy()

    # Compute unit tangents and normals at each vertex
    tangents = np.zeros_like(resampled)
    tangents[0] = resampled[1] - resampled[0]
    tangents[-1] = resampled[-1] - resampled[-2]
    if len(resampled) > 2:
        tangents[1:-1] = resampled[2:] - resampled[:-2]
    t_norms = np.hypot(tangents[:, 0], tangents[:, 1])
    t_norms = np.where(t_norms < 1e-9, 1.0, t_norms)
    tangents /= t_norms[:, None]
    normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))

    # Smooth normal displacement + gentle long-line bow
    noise = _smooth_value_noise_1d(s_vals, wavelength=25.0, rng=rng)
    bow_amp = float(rng.normal(0.0, 0.35 * jitter_mm)) * min(1.0, total_len / 30.0)
    u_norm = s_vals / total_len
    bow = bow_amp * np.sin(math.pi * u_norm)
    disp = (jitter_mm * 0.75 * noise) + bow
    if closed:
        # Keep closed loop seamless at seam
        disp[-1] = disp[0]

    out = resampled + normals * disp[:, None]

    # Subtle hand overshoot/undershoot at open endpoints
    if not closed and overshoot_mm > 1e-6 and total_len > 2.0:
        over0 = float(rng.uniform(-0.15, 1.0) * overshoot_mm)
        over1 = float(rng.uniform(-0.15, 1.0) * overshoot_mm)
        out[0] = out[0] - tangents[0] * over0
        out[-1] = out[-1] + tangents[-1] * over1

    if closed:
        out[-1] = out[0]

    return rdp_simplify(out, simplify_tol_mm)
