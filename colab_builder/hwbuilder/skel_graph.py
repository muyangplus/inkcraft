"""Skeleton junction graph contraction, multi-pass continuous chain merging, and heuristic ordering."""

from __future__ import annotations

import math

import numpy as np

from hwbuilder.skel_morph import pixel_neighbors


def polyline_length(pts: np.ndarray) -> float:
    if len(pts) < 2:
        return 0.0
    diffs = np.diff(pts.astype(np.float64), axis=0)
    return float(np.hypot(diffs[:, 0], diffs[:, 1]).sum())


def extract_contracted_skeleton_chains(skel: np.ndarray) -> list[np.ndarray]:
    """Trace skeleton graph while contracting every junction cluster (`deg >= 3`) to one centroid."""
    ys, xs = np.nonzero(skel)
    if len(ys) == 0:
        return []

    pts_set = set(zip(ys.tolist(), xs.tolist()))
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {
        p: pixel_neighbors(skel, p[0], p[1]) for p in pts_set
    }
    junc_px = {p for p, nb in adj.items() if len(nb) >= 3}

    cluster_of: dict[tuple[int, int], int] = {}
    centers: list[tuple[float, float]] = []
    visited_j: set[tuple[int, int]] = set()
    for p in sorted(junc_px):
        if p in visited_j:
            continue
        cid = len(centers)
        stack = [p]
        visited_j.add(p)
        comp: list[tuple[int, int]] = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            cluster_of[cur] = cid
            for nb in adj[cur]:
                if nb in junc_px and nb not in visited_j:
                    visited_j.add(nb)
                    stack.append(nb)
        cy = sum(q[0] for q in comp) / len(comp)
        cx = sum(q[1] for q in comp) / len(comp)
        centers.append((cx, cy))

    def _edge_key(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
        return (a, b) if a < b else (b, a)

    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    chains: list[np.ndarray] = []
    direct_cluster_pairs: set[tuple[int, int]] = set()

    for p in sorted(junc_px):
        c1 = cluster_of[p]
        for nb in adj[p]:
            if nb in junc_px:
                c2 = cluster_of[nb]
                if c2 != c1:
                    pair = (min(c1, c2), max(c1, c2))
                    if pair not in direct_cluster_pairs:
                        direct_cluster_pairs.add(pair)
                        chains.append(np.array([centers[c1], centers[c2]], dtype=np.float64))
                continue
            ek = _edge_key(p, nb)
            if ek in visited_edges:
                continue
            visited_edges.add(ek)
            pts_xy = [centers[c1], (float(nb[1]), float(nb[0]))]
            prev, cur = p, nb
            while True:
                cands = [n for n in adj[cur] if n != prev]
                if not cands:
                    break
                j_cands = [n for n in cands if n in junc_px]
                if j_cands:
                    nxt = j_cands[0]
                    ek_end = _edge_key(cur, nxt)
                    if ek_end not in visited_edges:
                        visited_edges.add(ek_end)
                    pts_xy.append(centers[cluster_of[nxt]])
                    break
                nxt = cands[0]
                ek2 = _edge_key(cur, nxt)
                if ek2 in visited_edges:
                    break
                visited_edges.add(ek2)
                pts_xy.append((float(nxt[1]), float(nxt[0])))
                prev, cur = cur, nxt
            if len(pts_xy) >= 2:
                chains.append(np.array(pts_xy, dtype=np.float64))

    for start in sorted(p for p, nb in adj.items() if len(nb) == 1):
        for nb in adj[start]:
            if nb in junc_px:
                continue
            ek = _edge_key(start, nb)
            if ek in visited_edges:
                continue
            visited_edges.add(ek)
            pts_xy = [(float(start[1]), float(start[0])), (float(nb[1]), float(nb[0]))]
            prev, cur = start, nb
            while True:
                cands = [n for n in adj[cur] if n != prev]
                if not cands:
                    break
                nxt = cands[0]
                if nxt in junc_px:
                    visited_edges.add(_edge_key(cur, nxt))
                    pts_xy.append(centers[cluster_of[nxt]])
                    break
                ek2 = _edge_key(cur, nxt)
                if ek2 in visited_edges:
                    break
                visited_edges.add(ek2)
                pts_xy.append((float(nxt[1]), float(nxt[0])))
                prev, cur = cur, nxt
            if len(pts_xy) >= 2:
                chains.append(np.array(pts_xy, dtype=np.float64))

    for start in sorted(pts_set):
        if start in junc_px:
            continue
        for nb in adj[start]:
            if nb in junc_px:
                continue
            ek = _edge_key(start, nb)
            if ek in visited_edges:
                continue
            visited_edges.add(ek)
            pts_xy = [(float(start[1]), float(start[0])), (float(nb[1]), float(nb[0]))]
            prev, cur = start, nb
            while True:
                cands = [n for n in adj[cur] if n != prev and n not in junc_px]
                if not cands:
                    break
                nxt = cands[0]
                ek2 = _edge_key(cur, nxt)
                if ek2 in visited_edges:
                    if nxt == start:
                        pts_xy.append((float(start[1]), float(start[0])))
                    break
                visited_edges.add(ek2)
                pts_xy.append((float(nxt[1]), float(nxt[0])))
                prev, cur = cur, nxt
                if cur == start:
                    break
            if len(pts_xy) >= 3:
                chains.append(np.array(pts_xy, dtype=np.float64))

    return chains


def _chain_endpoints_meta(
    c: np.ndarray,
) -> tuple[float, float, float, float, float, float, float, float, bool]:
    n = len(c)
    k = min(max(2, n // 5), min(6, n - 1))
    sx, sy = float(c[0, 0]), float(c[0, 1])
    dx0, dy0 = sx - float(c[k, 0]), sy - float(c[k, 1])
    n0 = math.hypot(dx0, dy0)
    stx, sty = (dx0 / n0, dy0 / n0) if n0 > 1e-9 else (0.0, 0.0)
    ex, ey = float(c[-1, 0]), float(c[-1, 1])
    dx1, dy1 = ex - float(c[-1 - k, 0]), ey - float(c[-1 - k, 1])
    n1 = math.hypot(dx1, dy1)
    etx, ety = (dx1 / n1, dy1 / n1) if n1 > 1e-9 else (0.0, 0.0)
    closed = math.hypot(sx - ex, sy - ey) < 1.5 and polyline_length(c) > 8.0
    return sx, sy, stx, sty, ex, ey, etx, ety, closed


def _join_pair(ci: np.ndarray, cj: np.ndarray, mode: int) -> np.ndarray:
    if mode == 0:
        a, b = ci, cj
    elif mode == 1:
        a, b = ci, cj[::-1]
    elif mode == 2:
        a, b = ci[::-1], cj
    else:
        a, b = cj, ci
    if math.hypot(float(a[-1, 0] - b[0, 0]), float(a[-1, 1] - b[0, 1])) < 0.8:
        return np.vstack([a, b[1:]])
    return np.vstack([a, b])


def merge_chains_continuous(chains: list[np.ndarray], scale_up: int = 1) -> list[np.ndarray]:
    """Multi-pass continuity merger: exact junction continuation, deg-2 corners, gap bridge, loops, & T-snaps."""
    work = [c.copy() for c in chains if len(c) >= 2]
    if len(work) <= 1:
        return work

    def _run_merge(join_r: float, max_turn_deg: float, only_deg2: bool = False) -> None:
        r2 = join_r * join_r
        cos_th = math.cos(math.radians(max_turn_deg))
        meta = [_chain_endpoints_meta(c) for c in work]

        for _ in range(200):
            m = len(work)
            if m <= 1:
                break

            deg_near: dict[tuple[int, int], int] | None = None
            if only_deg2:
                all_eps: list[tuple[int, int, float, float]] = []
                for idx_c, mt in enumerate(meta):
                    if mt[8]:
                        continue
                    all_eps.append((idx_c, 0, mt[0], mt[1]))
                    all_eps.append((idx_c, 1, mt[4], mt[5]))
                deg_near = {}
                for a_i, (ca, ea, xa, ya) in enumerate(all_eps):
                    cnt = 0
                    for b_i, (_, _, xb, yb) in enumerate(all_eps):
                        if a_i != b_i and (xa - xb) ** 2 + (ya - yb) ** 2 <= r2:
                            cnt += 1
                    deg_near[(ca, ea)] = cnt

            best_cost = 1e9
            best_pair: tuple[int, int, int] | None = None
            for i in range(m):
                isx, isy, istx, isty, iex, iey, ietx, iety, icl = meta[i]
                if icl:
                    continue
                for j in range(i + 1, m):
                    jsx, jsy, jstx, jsty, jex, jey, jetx, jety, jcl = meta[j]
                    if jcl:
                        continue
                    for mode, ei, ej, ax, ay, atx, aty, bx, by, btx, bty in (
                        (0, 1, 0, iex, iey, ietx, iety, jsx, jsy, jstx, jsty),
                        (1, 1, 1, iex, iey, ietx, iety, jex, jey, jetx, jety),
                        (2, 0, 0, isx, isy, istx, isty, jsx, jsy, jstx, jsty),
                        (3, 0, 1, isx, isy, istx, isty, jex, jey, jetx, jety),
                    ):
                        if deg_near is not None and (
                            deg_near.get((i, ei), 0) != 1 or deg_near.get((j, ej), 0) != 1
                        ):
                            continue
                        dx, dy = ax - bx, ay - by
                        d2 = dx * dx + dy * dy
                        if d2 > r2:
                            continue
                        align = -(atx * btx + aty * bty)
                        if align < cos_th:
                            continue
                        if d2 > 1.44 and not only_deg2:
                            dist = math.sqrt(d2)
                            gx, gy = (bx - ax) / dist, (by - ay) / dist
                            if (atx * gx + aty * gy) < 0.25 or (btx * (-gx) + bty * (-gy)) < 0.25:
                                continue
                        cost = math.sqrt(d2) * 1.5 + (1.0 - align) * 3.0
                        if cost < best_cost:
                            best_cost = cost
                            best_pair = (i, j, mode)

            if best_pair is None:
                break
            bi, bj, mode = best_pair
            mc = _join_pair(work[bi], work[bj], mode)
            work[bi] = mc
            meta[bi] = _chain_endpoints_meta(mc)
            del work[bj]
            del meta[bj]

    _run_merge(join_r=1.4, max_turn_deg=62.0, only_deg2=False)
    _run_merge(join_r=1.6, max_turn_deg=145.0, only_deg2=True)
    _run_merge(join_r=max(3.5, 2.4 * scale_up), max_turn_deg=60.0, only_deg2=False)
    _run_merge(join_r=max(2.2, 1.5 * scale_up), max_turn_deg=140.0, only_deg2=True)

    loop_r = max(4.0, 2.6 * scale_up)
    for i in range(len(work)):
        c = work[i]
        d_se = math.hypot(float(c[0, 0] - c[-1, 0]), float(c[0, 1] - c[-1, 1]))
        if 1.0 < d_se <= loop_r and polyline_length(c) > d_se * 3.2:
            work[i] = np.vstack([c, c[0:1]])

    # Pass 3: Snap detached free endpoints onto nearest interior stroke point at T-junctions
    # Closed loops (0, 口, 日) are skipped so their closed seam is never pulled outward.
    snap_r = max(3.5, 2.2 * scale_up)
    for i in range(len(work)):
        ci = work[i]
        if len(ci) < 2:
            continue
        d_se = math.hypot(float(ci[0, 0] - ci[-1, 0]), float(ci[0, 1] - ci[-1, 1]))
        if d_se < 1.5 and polyline_length(ci) > 8.0:
            continue
        for is_start in (True, False):
            p = ci[0] if is_start else ci[-1]
            min_d = 1e9
            best_pt: np.ndarray | None = None
            k = min(3, len(ci) - 1)
            out_v = (ci[0] - ci[k]) if is_start else (ci[-1] - ci[-1 - k])
            ov_n = float(np.hypot(out_v[0], out_v[1]))
            out_u = out_v / ov_n if ov_n > 1e-6 else np.zeros(2, dtype=np.float64)
            for j in range(len(work)):
                if j == i:
                    continue
                cj = work[j]
                diffs = cj - p
                ds = np.hypot(diffs[:, 0], diffs[:, 1])
                idx_m = int(np.argmin(ds))
                d = float(ds[idx_m])
                if d < min_d:
                    min_d = d
                    best_pt = cj[idx_m]
            if 1.0 < min_d <= snap_r and best_pt is not None:
                dir_v = (best_pt - p) / min_d
                if float(np.dot(out_u, dir_v)) > 0.25 or min_d <= 1.6 * scale_up:
                    if is_start:
                        work[i] = np.vstack([best_pt[None, :], ci])
                    else:
                        work[i] = np.vstack([ci, best_pt[None, :]])
                    ci = work[i]

    if len(work) > 1:
        kept = [c for c in work if polyline_length(c) >= 1.8 * scale_up]
        if kept:
            work = kept
    return work


def smooth_preserve_corners(
    pts: np.ndarray,
    corner_deg: float = 55.0,
    iterations: int = 2,
) -> np.ndarray:
    """Endpoint-preserving polyline smoothing that leaves sharp corners untouched."""
    if len(pts) < 4:
        return pts
    cos_c = math.cos(math.radians(corner_deg))
    out = pts.astype(np.float64, copy=True)
    for _ in range(iterations):
        nxt = out.copy()
        for k in range(1, len(out) - 1):
            v1 = out[k] - out[k - 1]
            v2 = out[k + 1] - out[k]
            n1 = math.hypot(float(v1[0]), float(v1[1]))
            n2 = math.hypot(float(v2[0]), float(v2[1]))
            if n1 > 1e-6 and n2 > 1e-6:
                if (float(v1[0]) * float(v2[0]) + float(v1[1]) * float(v2[1])) / (n1 * n2) < cos_c:
                    continue
            nxt[k] = 0.25 * out[k - 1] + 0.5 * out[k] + 0.25 * out[k + 1]
        out = nxt
    return out


def order_and_orient_heuristic(strokes: list[np.ndarray]) -> list[np.ndarray]:
    """Order strokes top-to-bottom, left-to-right and orient L->R / T->B."""
    oriented: list[np.ndarray] = []
    for s in strokes:
        if len(s) < 2:
            continue
        dx = float(s[-1, 0] - s[0, 0])
        dy = float(s[-1, 1] - s[0, 1])
        if abs(dx) >= abs(dy) * 1.15:
            if dx < 0:
                s = s[::-1]
        else:
            if dy < 0:
                s = s[::-1]
        oriented.append(s)

    oriented.sort(key=lambda s: (round(float(s[0, 1]) / 12.0), float(s[0, 0])))
    return oriented
