"""Morphological thinning, Chamfer distance transform, closing, and spur pruning."""

from __future__ import annotations

import math

import numpy as np


def zhang_suen_thin(binary_mask: np.ndarray, max_iter: int = 64) -> np.ndarray:
    """Pure-NumPy vectorized Zhang-Suen morphological thinning (`True` = foreground)."""
    img = np.pad(binary_mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    for _ in range(max_iter):
        changed = False
        for step in (0, 1):
            p2 = img[:-2, 1:-1]
            p3 = img[:-2, 2:]
            p4 = img[1:-1, 2:]
            p5 = img[2:, 2:]
            p6 = img[2:, 1:-1]
            p7 = img[2:, :-2]
            p8 = img[1:-1, :-2]
            p9 = img[:-2, :-2]
            center = img[1:-1, 1:-1]

            neighbors = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            transitions = (
                ((p2 == 0) & (p3 == 1)).astype(np.uint8)
                + ((p3 == 0) & (p4 == 1)).astype(np.uint8)
                + ((p4 == 0) & (p5 == 1)).astype(np.uint8)
                + ((p5 == 0) & (p6 == 1)).astype(np.uint8)
                + ((p6 == 0) & (p7 == 1)).astype(np.uint8)
                + ((p7 == 0) & (p8 == 1)).astype(np.uint8)
                + ((p8 == 0) & (p9 == 1)).astype(np.uint8)
                + ((p9 == 0) & (p2 == 1)).astype(np.uint8)
            )
            if step == 0:
                cond3 = (p2 * p4 * p6) == 0
                cond4 = (p4 * p6 * p8) == 0
            else:
                cond3 = (p2 * p4 * p8) == 0
                cond4 = (p2 * p6 * p8) == 0

            remove = (
                (center == 1)
                & (neighbors >= 2)
                & (neighbors <= 6)
                & (transitions == 1)
                & cond3
                & cond4
            )
            if np.any(remove):
                img[1:-1, 1:-1][remove] = 0
                changed = True
        if not changed:
            break
    return img[1:-1, 1:-1].astype(bool)


def chamfer_distance_transform(binary_mask: np.ndarray) -> np.ndarray:
    """Fast pure-NumPy 2-pass Chamfer 3-4 distance transform inside foreground (`True`) pixels."""
    h, w = binary_mask.shape
    inf = float(h + w) * 4.0
    dist = np.where(binary_mask, inf, 0.0).astype(np.float32)

    for y in range(h):
        for x in range(w):
            if dist[y, x] == 0.0:
                continue
            d = dist[y, x]
            if y > 0:
                d = min(d, dist[y - 1, x] + 1.0)
                if x > 0:
                    d = min(d, dist[y - 1, x - 1] + 1.4142)
                if x + 1 < w:
                    d = min(d, dist[y - 1, x + 1] + 1.4142)
            if x > 0:
                d = min(d, dist[y, x - 1] + 1.0)
            dist[y, x] = d

    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            if dist[y, x] == 0.0:
                continue
            d = dist[y, x]
            if y + 1 < h:
                d = min(d, dist[y + 1, x] + 1.0)
                if x > 0:
                    d = min(d, dist[y + 1, x - 1] + 1.4142)
                if x + 1 < w:
                    d = min(d, dist[y + 1, x + 1] + 1.4142)
            if x + 1 < w:
                d = min(d, dist[y, x + 1] + 1.0)
            dist[y, x] = d

    return dist


def pixel_neighbors(skel: np.ndarray, y: int, x: int) -> list[tuple[int, int]]:
    h, w = skel.shape
    out: list[tuple[int, int]] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and skel[ny, nx]:
                out.append((ny, nx))
    return out


def prune_skeleton_spurs(skel: np.ndarray, max_spur_len_px: float) -> np.ndarray:
    """Iteratively remove short terminal spurs connected to junctions."""
    if max_spur_len_px <= 1.0 or not skel.any():
        return skel.copy()

    cur = skel.copy()
    for _ in range(4):
        ys, xs = np.nonzero(cur)
        if len(ys) == 0:
            break
        pts = set(zip(ys.tolist(), xs.tolist()))
        adj = {p: pixel_neighbors(cur, p[0], p[1]) for p in pts}
        endpoints = [p for p, nb in adj.items() if len(nb) == 1]
        junctions = {p for p, nb in adj.items() if len(nb) >= 3}
        removed_any = False

        for ep in endpoints:
            if not cur[ep[0], ep[1]]:
                continue
            path = [ep]
            prev = None
            node = ep
            length = 0.0
            hit_junction = False
            while True:
                nbs = [n for n in adj.get(node, []) if n != prev and cur[n[0], n[1]]]
                if len(nbs) != 1:
                    break
                nxt = nbs[0]
                length += math.hypot(nxt[0] - node[0], nxt[1] - node[1])
                if nxt in junctions:
                    hit_junction = True
                    break
                path.append(nxt)
                if length > max_spur_len_px:
                    break
                prev, node = node, nxt

            if hit_junction and length <= max_spur_len_px:
                for py, px in path:
                    cur[py, px] = False
                removed_any = True
        if not removed_any:
            break
    return cur


def morph_close_3x3(mask: np.ndarray) -> np.ndarray:
    """3x3 cross closing to heal 1px ink fractures without fusing parallel strokes."""
    if mask.shape[0] < 3 or mask.shape[1] < 3:
        return mask
    p = np.pad(mask, 1, mode="constant", constant_values=False)
    dil = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    p2 = np.pad(dil, 1, mode="constant", constant_values=False)
    ero = p2[1:-1, 1:-1] & p2[:-2, 1:-1] & p2[2:, 1:-1] & p2[1:-1, :-2] & p2[1:-1, 2:]
    return mask | ero
