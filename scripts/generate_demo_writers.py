#!/usr/bin/env python3
"""Generate 3 distinct multi-variant demo .hwfont files into ./fonts/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "hwfont_sdk"))
sys.path.insert(0, str(ROOT / "backend"))

from inkcraft.writers.fallback.hershey import BUILTIN_GLYPHS  # noqa: E402
from hwfont_sdk import HwFontMeta, HwFontReader, HwFontWriter  # noqa: E402


@dataclass
class WriterStyle:
    filename: str
    writer_id: str
    writer_name: str
    writer_alias: str
    author: str
    style_tags: list[str]
    slant_deg: float
    x_scale: float
    y_scale: float
    jitter_u: float
    curve_u: float
    variants: int
    seed: int
    preview_char: str


STYLES = [
    WriterStyle(
        filename="lin_kaishu.hwfont",
        writer_id="11111111-1111-4111-8111-111111111101",
        writer_name="林清河",
        writer_alias="行楷·端正笔记体",
        author="Handwrite Studio",
        style_tags=["行楷", "工整", "理工笔记"],
        slant_deg=2.2,
        x_scale=0.98,
        y_scale=1.00,
        jitter_u=11.0,
        curve_u=10.0,
        variants=4,
        seed=101,
        preview_char="永",
    ),
    WriterStyle(
        filename="chen_xingshu.hwfont",
        writer_id="22222222-2222-4222-8222-222222222202",
        writer_name="陈墨白",
        writer_alias="行书·右倾流畅体",
        author="Handwrite Studio",
        style_tags=["行书", "偏右倾", "连贯流畅"],
        slant_deg=7.5,
        x_scale=1.03,
        y_scale=0.95,
        jitter_u=18.0,
        curve_u=18.0,
        variants=4,
        seed=202,
        preview_char="和",
    ),
    WriterStyle(
        filename="su_engineering.hwfont",
        writer_id="33333333-3333-4333-8333-333333333303",
        writer_name="苏工图",
        writer_alias="仿宋·紧凑工程体",
        author="Handwrite Studio",
        style_tags=["工程字", "紧凑", "竖直清晰"],
        slant_deg=-0.8,
        x_scale=0.91,
        y_scale=1.04,
        jitter_u=6.0,
        curve_u=5.0,
        variants=3,
        seed=303,
        preview_char="实",
    ),
]


def _stylize_stroke(
    pts: np.ndarray,
    rng: np.random.Generator,
    style: WriterStyle,
    variant_no: int,
) -> np.ndarray:
    arr = pts.astype(np.float64).copy()
    # Subdivide long segments to allow natural slight arc
    if len(arr) == 2 and float(np.linalg.norm(arr[1] - arr[0])) > 120.0:
        mid = 0.5 * (arr[0] + arr[1])
        d = arr[1] - arr[0]
        normal = np.array([-d[1], d[0]])
        norm_len = float(np.linalg.norm(normal))
        if norm_len > 1e-6:
            normal /= norm_len
            mid = mid + normal * rng.normal(0.0, style.curve_u)
        arr = np.vstack([arr[0], mid, arr[1]])

    # Apply writer affine style around (500, 500)
    cx, cy = 500.0, 500.0
    dx = (arr[:, 0] - cx) * (style.x_scale + rng.normal(0.0, 0.02))
    dy = (arr[:, 1] - cy) * (style.y_scale + rng.normal(0.0, 0.02))
    shear = np.tan(np.deg2rad(style.slant_deg + rng.normal(0.0, 0.9)))
    x_new = cx + dx + shear * (800.0 - (cy + dy)) * 0.45
    y_new = cy + dy

    # Subtle variant-level endpoint & body organic jitter
    scale_v = 0.65 if variant_no == 0 else 1.0
    x_new += rng.normal(0.0, style.jitter_u * scale_v, size=len(arr))
    y_new += rng.normal(0.0, style.jitter_u * scale_v, size=len(arr))

    out = np.column_stack([x_new, y_new])
    out = np.clip(np.rint(out), 0, 1000).astype(np.int16)
    return out


def generate_all(out_dir: Path | None = None) -> list[Path]:
    fonts_dir = out_dir or (ROOT / "fonts")
    fonts_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    for style in STYLES:
        rng = np.random.default_rng(style.seed)
        meta = HwFontMeta(
            writer_id=style.writer_id,
            writer_name=style.writer_name,
            writer_alias=style.writer_alias,
            author=style.author,
            version="1.0.0",
            style_tags=style.style_tags,
            units_per_em=1000,
            baseline_y=800,
            x_height=440,
            cap_height=680,
            default_advance=1000,
            builder="generate_demo_writers.py 1.0.0",
            model="parametric-single-line-seed",
            preview_text="永和九年，实验报告 y=∫f(x)dx",
            preview_char=style.preview_char,
        )
        out_path = fonts_dir / style.filename
        writer = HwFontWriter(out_path, meta)

        for ch, (adv, raw_strokes) in BUILTIN_GLYPHS.items():
            if ch in (" ", "\u3000"):
                continue
            for vno in range(style.variants):
                styled = [
                    _stylize_stroke(np.asarray(s, dtype=np.int16), rng, style, vno)
                    for s in raw_strokes
                ]
                v_adv = int(round(adv * style.x_scale))
                src = "scan" if vno == 0 else "generated"
                writer.add_variant(
                    ch,
                    styled,
                    source=src,
                    quality=0.98 if vno == 0 else round(float(rng.uniform(0.90, 0.97)), 3),
                    weight=1.0,
                    advance=max(200, min(1400, v_adv)),
                )

        # Common Latin kerning pairs
        for l_ch, r_ch, adj in [("A", "V", -55), ("V", "A", -55), ("T", "o", -45), ("W", "a", -35)]:
            writer.set_kerning(l_ch, r_ch, adj)

        final_path = writer.finalize()
        with HwFontReader(final_path) as reader:
            report = reader.verify()
            if not report.ok:
                raise RuntimeError(f"Verification failed for {final_path}: {report.errors}")
            print(
                f"OK {final_path.name}: glyphs={report.glyph_count}, "
                f"variants={report.variant_count}, sha256={report.actual_sha256[:12]}..."
            )
        generated.append(final_path)

    return generated


if __name__ == "__main__":
    generate_all()
