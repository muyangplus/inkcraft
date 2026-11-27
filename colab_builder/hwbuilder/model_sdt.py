"""Few-shot Style-Disentangled Trajectory (SDT) model & local CPU style-transfer augmentor.

Provides two seamlessly compatible engines:
  1. **Colab GPU Engine (`SDTTrainer` / `build_sdt_model`)**: Lazy-imported PyTorch 2.x
     Style-Disentangled Transformer with LoRA adapters for few-shot writer fine-tuning
     and autoregressive `(dx, dy, pen_state)` trajectory generation.
  2. **Local CPU Engine (`LocalStyleTransferAugmentor`)**: Pure-NumPy parametric writer-style
     learner & multi-variant trajectory synthesizer that extracts slant, aspect ratio,
     curvature, endpoint overshoot, and jitter statistics from scanned strokes so the entire
     builder pipeline can be tested and run without a GPU.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from hwbuilder.skeleton_align import rdp_simplify, resample_stroke


# ---------------------------------------------------------------------------
# Trajectory <-> (dx, dy, pen_state) sequence codec
# pen_state: 0 = pen_down (continue stroke), 1 = pen_lift (end stroke), 2 = end_of_char
# ---------------------------------------------------------------------------

def strokes_to_delta_seq(
    strokes: Sequence[np.ndarray],
    scale: float = 1000.0,
) -> np.ndarray:
    """Convert `0..1000` strokes into float32 sequence of `(dx, dy, p_down, p_lift, p_end)`.

    First point starts from `(0.0, 0.0)` so the sequence is fully invertible via cumsum.
    """
    rows: list[list[float]] = []
    prev_x, prev_y = 0.0, 0.0
    valid = [np.asarray(s, dtype=np.float64) for s in strokes if len(s) >= 2]
    for s_idx, stroke in enumerate(valid):
        is_last_stroke = s_idx == len(valid) - 1
        for p_idx in range(len(stroke)):
            x = float(stroke[p_idx, 0]) / scale
            y = float(stroke[p_idx, 1]) / scale
            dx = x - prev_x
            dy = y - prev_y
            prev_x, prev_y = x, y
            is_last_pt = p_idx == len(stroke) - 1
            if is_last_pt and is_last_stroke:
                state = [0.0, 0.0, 1.0]
            elif is_last_pt:
                state = [0.0, 1.0, 0.0]
            else:
                state = [1.0, 0.0, 0.0]
            rows.append([dx, dy, *state])
    if not rows:
        return np.zeros((1, 5), dtype=np.float32)
    return np.asarray(rows, dtype=np.float32)


def delta_seq_to_strokes(
    seq: np.ndarray,
    scale: float = 1000.0,
) -> list[np.ndarray]:
    """Decode `(dx, dy, p_down, p_lift, p_end)` sequence back into `0..1000` int16 strokes."""
    arr = np.asarray(seq, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] < 5 or len(arr) == 0:
        return []

    strokes: list[np.ndarray] = []
    cur: list[list[float]] = []
    x, y = 0.0, 0.0
    for row in arr:
        x += float(row[0]) * scale
        y += float(row[1]) * scale
        cur.append([max(0.0, min(1000.0, x)), max(0.0, min(1000.0, y))])
        state = int(np.argmax(row[2:5]))
        if state == 1:  # pen_lift
            if len(cur) >= 2:
                strokes.append(np.rint(np.asarray(cur)).astype(np.int16))
            cur = []
        elif state == 2:  # end_of_char
            if len(cur) >= 2:
                strokes.append(np.rint(np.asarray(cur)).astype(np.int16))
            cur = []
            break
    if len(cur) >= 2:
        strokes.append(np.rint(np.asarray(cur)).astype(np.int16))
    return strokes


# ---------------------------------------------------------------------------
# Local CPU Parametric Style-Transfer & Multi-Variant Augmentation Engine
# ---------------------------------------------------------------------------

@dataclass
class WriterStyleProfile:
    """Learned parametric writer handwriting statistics (JSON-serializable)."""

    writer_name: str = "unnamed_writer"
    slant_deg: float = 2.0
    slant_std_deg: float = 1.6
    aspect_x: float = 1.0
    aspect_y: float = 1.0
    curvature_u: float = 12.0
    jitter_u: float = 7.5
    endpoint_overshoot_u: float = 9.0
    stroke_shift_u: float = 14.0
    scale_jitter: float = 0.035
    y_offset_u: float = 0.0
    sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> WriterStyleProfile:
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))


class LocalStyleTransferAugmentor:
    """CPU-runnable parametric style transfer and multi-variant stroke synthesizer.

    Fits writer slant, aspect ratio, stroke bow/curvature, and micro-jitter from real
    scanned trajectories, then transfers that style onto any template or scanned glyph to
    synthesize diverse, arm-friendly multi-variant trajectories (`同字异形`).
    """

    def __init__(self, profile: WriterStyleProfile | None = None) -> None:
        self.profile = profile or WriterStyleProfile()

    def fit(
        self,
        scanned_glyphs: Mapping[str, Sequence[Sequence[np.ndarray]]] | Sequence[Sequence[np.ndarray]],
        *,
        writer_name: str | None = None,
    ) -> WriterStyleProfile:
        """Estimate writer style parameters from scanned stroke sequences."""
        glyph_list: list[list[np.ndarray]] = []
        if isinstance(scanned_glyphs, Mapping):
            for variants in scanned_glyphs.values():
                for v in variants:
                    if v and isinstance(v[0], np.ndarray) and v[0].ndim == 2:
                        glyph_list.append([np.asarray(s, dtype=np.float64) for s in v if len(s) >= 2])
                    elif isinstance(v, np.ndarray) and v.ndim == 2:
                        # Single variant passed as list[ndarray]
                        glyph_list.append([np.asarray(s, dtype=np.float64) for s in variants if len(s) >= 2])  # type: ignore[arg-type]
                        break
        else:
            for item in scanned_glyphs:
                arrs = [np.asarray(s, dtype=np.float64) for s in item if len(s) >= 2]
                if arrs:
                    glyph_list.append(arrs)

        if not glyph_list:
            if writer_name:
                self.profile.writer_name = writer_name
            return self.profile

        slants: list[float] = []
        aspects: list[float] = []
        curvatures: list[float] = []
        y_centers: list[float] = []

        for strokes in glyph_list:
            pts_all = np.vstack(strokes)
            w = max(10.0, float(pts_all[:, 0].max() - pts_all[:, 0].min()))
            h = max(10.0, float(pts_all[:, 1].max() - pts_all[:, 1].min()))
            aspects.append(w / h)
            y_centers.append(float(pts_all[:, 1].mean()) - 500.0)

            for s in strokes:
                vec = s[-1] - s[0]
                length = float(np.linalg.norm(vec))
                if length < 60.0:
                    continue
                # Vertical-ish strokes reveal writer slant angle
                if abs(vec[1]) > abs(vec[0]) * 1.4:
                    # Positive slant_deg means top leans right (italic right slant)
                    angle_deg = math.degrees(math.atan2(-(s[-1, 0] - s[0, 0]), abs(s[-1, 1] - s[0, 1])))
                    if -22.0 <= angle_deg <= 22.0:
                        slants.append(angle_deg)
                # Curvature: max perpendicular deviation from chord
                if len(s) >= 3:
                    unit = vec / length
                    rel = s[1:-1] - s[0]
                    perp = np.abs(rel[:, 0] * unit[1] - rel[:, 1] * unit[0])
                    curvatures.append(float(perp.max()))

        mean_slant = float(np.median(slants)) if slants else 2.0
        std_slant = float(np.clip(np.std(slants), 1.0, 4.5)) if len(slants) >= 3 else 1.8
        med_aspect = float(np.clip(np.median(aspects), 0.78, 1.25)) if aspects else 1.0
        med_curve = float(np.clip(np.median(curvatures), 5.0, 28.0)) if curvatures else 11.0
        med_y_off = float(np.clip(np.median(y_centers), -45.0, 45.0)) if y_centers else 0.0

        self.profile = WriterStyleProfile(
            writer_name=writer_name or self.profile.writer_name,
            slant_deg=round(mean_slant, 3),
            slant_std_deg=round(std_slant, 3),
            aspect_x=round(math.sqrt(med_aspect), 3),
            aspect_y=round(1.0 / math.sqrt(med_aspect), 3),
            curvature_u=round(med_curve, 2),
            jitter_u=round(max(4.5, min(14.0, med_curve * 0.65)), 2),
            endpoint_overshoot_u=round(max(5.0, min(18.0, med_curve * 0.75)), 2),
            stroke_shift_u=round(max(8.0, min(22.0, med_curve * 1.05)), 2),
            scale_jitter=0.038,
            y_offset_u=round(med_y_off, 2),
            sample_count=len(glyph_list),
        )
        return self.profile

    def _transform_single_variant(
        self,
        base_strokes: Sequence[np.ndarray],
        rng: np.random.Generator,
        diversity_boost: float = 1.0,
    ) -> list[np.ndarray]:
        p = self.profile
        # Sample coherent per-glyph latent style deviations
        slant_rad = math.radians(p.slant_deg + rng.normal(0.0, p.slant_std_deg * diversity_boost))
        tan_s = math.tan(slant_rad)
        sx = p.aspect_x * (1.0 + rng.uniform(-p.scale_jitter, p.scale_jitter) * diversity_boost)
        sy = p.aspect_y * (1.0 + rng.uniform(-p.scale_jitter, p.scale_jitter) * diversity_boost)
        rot_rad = math.radians(rng.normal(0.0, 1.8 * diversity_boost))
        cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
        gx = float(rng.normal(0.0, 14.0 * diversity_boost))
        gy = float(p.y_offset_u * 0.25 + rng.normal(0.0, 14.0 * diversity_boost))

        valid = [np.asarray(s, dtype=np.float64) for s in base_strokes if len(s) >= 2]
        if not valid:
            return []
        all_pts = np.vstack(valid)
        cx = float(all_pts[:, 0].mean())
        cy = float(all_pts[:, 1].mean())
        min_xy = all_pts.min(axis=0)
        warp_span = np.maximum(all_pts.max(axis=0) - min_xy, 50.0)

        # Detect which stroke endpoints sit near another stroke (or self-loop opposite end)
        is_free_start: list[bool] = []
        is_free_end: list[bool] = []
        for idx_i, si in enumerate(valid):
            others = [sj for idx_j, sj in enumerate(valid) if idx_j != idx_i]
            other_pts = np.vstack(others) if others else np.empty((0, 2), dtype=np.float64)
            ps, pe = si[0], si[-1]
            d_self = float(np.hypot(pe[0] - ps[0], pe[1] - ps[1]))
            min_s = float(np.min(np.hypot(*(other_pts - ps).T))) if len(other_pts) else 1e9
            min_e = float(np.min(np.hypot(*(other_pts - pe).T))) if len(other_pts) else 1e9
            if d_self <= 24.0:
                min_s = min(min_s, d_self)
                min_e = min(min_e, d_self)
            is_free_start.append(min_s > 24.0)
            is_free_end.append(min_e > 24.0)

        # Glyph-wide continuous 2D spatial warp field (preserves all touching junctions exactly)
        amp_w = min(22.0, p.stroke_shift_u * 1.15) * diversity_boost
        ax1, ay1 = rng.normal(0.0, amp_w * 0.72, size=2)
        ax2, ay2 = rng.normal(0.0, amp_w * 0.55, size=2)
        fx1, fy1 = float(rng.uniform(1.2, 2.6)), float(rng.uniform(1.2, 2.6))
        fx2, fy2 = float(rng.uniform(1.5, 3.2)), float(rng.uniform(1.5, 3.2))
        ph1, ph2 = float(rng.uniform(0.0, 2.0 * math.pi)), float(rng.uniform(0.0, 2.0 * math.pi))

        out: list[np.ndarray] = []
        for idx_i, s in enumerate(valid):
            # Subdivide straight 2-point strokes so bowing/curvature appears organic
            pts = resample_stroke(s, min_dist=5.0, max_dist=38.0, max_points=64)
            n = len(pts)
            t = np.linspace(0.0, 1.0, n)

            vec = pts[-1] - pts[0]
            chord_len = float(np.linalg.norm(vec))
            if chord_len > 1e-3:
                perp = np.array([-vec[1] / chord_len, vec[0] / chord_len], dtype=np.float64)
                tangent = vec / chord_len
            else:
                perp = np.array([0.0, 1.0], dtype=np.float64)
                tangent = np.array([1.0, 0.0], dtype=np.float64)

            # Endpoint-pinned quadratic bow (zero at t=0 and t=1)
            bow_amp = float(rng.normal(0.0, p.curvature_u * diversity_boost))
            bow = (4.0 * t * (1.0 - t))[:, None] * (bow_amp * perp[None, :])
            bow[0] = 0.0
            bow[-1] = 0.0

            # Gentle tangent overshoot only on free non-junction endpoints
            over_start = (
                float(rng.normal(0.0, p.endpoint_overshoot_u * 0.45 * diversity_boost))
                if is_free_start[idx_i]
                else 0.0
            )
            over_end = (
                float(rng.normal(0.0, p.endpoint_overshoot_u * 0.45 * diversity_boost))
                if is_free_end[idx_i]
                else 0.0
            )
            over = ((1.0 - t) * (-over_start) + t * over_end)[:, None] * tangent[None, :]

            # Endpoint-zero smooth wave (zero at t=0 and t=1 -> junctions never pull apart)
            wave = np.sin(math.pi * t)[:, None] * rng.normal(
                0.0, p.jitter_u * 0.55 * diversity_boost, size=(1, 2)
            )
            wave[0] = 0.0
            wave[-1] = 0.0

            warped = pts + bow + over + wave

            # Apply coherent 2D spatial warp evaluated at original glyph coordinates
            u = (pts[:, 0] - min_xy[0]) / warp_span[0]
            v = (pts[:, 1] - min_xy[1]) / warp_span[1]
            m1 = np.sin(math.pi * fx1 * u + math.pi * fy1 * v + ph1)
            m2 = np.cos(math.pi * fx2 * u - math.pi * fy2 * v + ph2)
            warped[:, 0] += ax1 * m1 + ax2 * m2
            warped[:, 1] += ay1 * m1 + ay2 * m2

            # Apply global writer slant, scale, rotation around glyph centroid
            rel_x = (warped[:, 0] - cx) * sx
            rel_y = (warped[:, 1] - cy) * sy
            sheared_x = rel_x - tan_s * rel_y
            sheared_y = rel_y
            rot_x = sheared_x * cos_r - sheared_y * sin_r + cx + gx
            rot_y = sheared_x * sin_r + sheared_y * cos_r + cy + gy

            final = np.column_stack([rot_x, rot_y])
            final = rdp_simplify(final, epsilon=2.4)
            final = resample_stroke(final, min_dist=4.0, max_dist=38.0, max_points=105)
            out.append(np.clip(np.rint(final), 0, 1000).astype(np.int16))

        return out

    def synthesize_variants(
        self,
        char: str,
        base_strokes: Sequence[np.ndarray],
        *,
        n_variants: int = 4,
        seed: int = 42,
        include_original: bool = False,
        diversity_boost: float = 1.0,
    ) -> list[list[np.ndarray]]:
        """Synthesize `n_variants` style-consistent handwriting variants for `char`."""
        valid_base = [np.asarray(s, dtype=np.float64) for s in base_strokes if len(s) >= 2]
        if not valid_base:
            return []

        digest = hashlib.sha256(f"{seed}:{char}:{self.profile.writer_name}".encode("utf-8")).digest()
        char_seed = int.from_bytes(digest[:8], "little")
        rng = np.random.default_rng(char_seed)

        results: list[list[np.ndarray]] = []
        if include_original:
            orig = [np.clip(np.rint(s), 0, 1000).astype(np.int16) for s in valid_base]
            if orig:
                results.append(orig)

        attempts = 0
        max_attempts = max(4, n_variants * 3)
        while len(results) < n_variants and attempts < max_attempts:
            attempts += 1
            boost = diversity_boost * (0.9 + 0.25 * len(results))
            cand = self._transform_single_variant(valid_base, rng, diversity_boost=boost)
            if cand:
                results.append(cand)
        return results


# ---------------------------------------------------------------------------
# PyTorch Few-Shot SDT + LoRA Interface (Lazy `torch` import for Colab GPU)
# ---------------------------------------------------------------------------

def is_torch_available() -> bool:
    """Return True if PyTorch is installed in the current Python runtime."""
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _require_torch() -> Any:
    try:
        import torch
        return torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is not installed in this environment. "
            "Run inside Google Colab (GPU) for SDT neural training, or use "
            "`LocalStyleTransferAugmentor` for local CPU style synthesis."
        ) from exc


@dataclass
class SDTConfig:
    """Hyperparameters for the PyTorch Style-Disentangled Trajectory (SDT) Transformer."""

    d_model: int = 256
    nhead: int = 8
    num_encoder_layers: int = 4
    num_decoder_layers: int = 4
    dim_feedforward: int = 1024
    dropout: float = 0.1
    style_dim: int = 128
    latent_dim: int = 32
    max_seq_len: int = 256
    lora_rank: int = 8
    lora_alpha: float = 16.0
    lr: float = 2e-4
    weight_decay: float = 1e-4
    epochs: int = 60
    batch_size: int = 16
    grad_clip: float = 1.0
    device: str = "auto"


def build_sdt_model(cfg: SDTConfig | None = None) -> Any:
    """Build the PyTorch `SDTTrajectoryModel` with LoRA adapters (requires `torch`)."""
    torch = _require_torch()
    nn = torch.nn
    F = torch.nn.functional
    config = cfg or SDTConfig()

    class LoRALinear(nn.Module):
        """Drop-in Linear layer augmented with trainable low-rank adapters `(A, B)`."""

        def __init__(self, in_features: int, out_features: int, rank: int = 8, alpha: float = 16.0) -> None:
            super().__init__()
            self.base = nn.Linear(in_features, out_features)
            self.rank = rank
            self.scaling = alpha / max(1, rank)
            self.lora_a = nn.Parameter(torch.randn(rank, in_features) * 0.02)
            self.lora_b = nn.Parameter(torch.zeros(out_features, rank))

        def forward(self, x: Any) -> Any:
            base_out = self.base(x)
            lora_out = F.linear(F.linear(x, self.lora_a), self.lora_b) * self.scaling
            return base_out + lora_out

    class SDTTrajectoryModel(nn.Module):
        """Style-Disentangled Transformer generating `(dx, dy, pen_state)` sequences."""

        def __init__(self, c: SDTConfig) -> None:
            super().__init__()
            self.cfg = c
            self.input_proj = LoRALinear(5, c.d_model, rank=c.lora_rank, alpha=c.lora_alpha)
            self.content_proj = nn.Linear(5, c.d_model)
            self.pos_emb = nn.Embedding(c.max_seq_len, c.d_model)

            # Style encoder summarizes writer reference trajectories -> style vector
            style_layer = nn.TransformerEncoderLayer(
                d_model=c.d_model, nhead=c.nhead, dim_feedforward=c.dim_feedforward,
                dropout=c.dropout, batch_first=True,
            )
            self.style_encoder = nn.TransformerEncoder(style_layer, num_layers=2)
            self.style_head = LoRALinear(c.d_model, c.style_dim, rank=c.lora_rank, alpha=c.lora_alpha)

            # Content encoder encodes canonical template strokes
            content_layer = nn.TransformerEncoderLayer(
                d_model=c.d_model, nhead=c.nhead, dim_feedforward=c.dim_feedforward,
                dropout=c.dropout, batch_first=True,
            )
            self.content_encoder = nn.TransformerEncoder(content_layer, num_layers=c.num_encoder_layers)

            # Style + latent z fusion token prepended to cross-attention memory
            self.cond_proj = LoRALinear(c.style_dim + c.latent_dim, c.d_model, rank=c.lora_rank, alpha=c.lora_alpha)

            # Autoregressive trajectory decoder
            dec_layer = nn.TransformerDecoderLayer(
                d_model=c.d_model, nhead=c.nhead, dim_feedforward=c.dim_feedforward,
                dropout=c.dropout, batch_first=True,
            )
            self.decoder = nn.TransformerDecoder(dec_layer, num_layers=c.num_decoder_layers)
            self.delta_head = LoRALinear(c.d_model, 2, rank=c.lora_rank, alpha=c.lora_alpha)
            self.state_head = LoRALinear(c.d_model, 3, rank=c.lora_rank, alpha=c.lora_alpha)

        def encode_style(self, style_seq: Any, style_pad_mask: Any | None = None) -> Any:
            b, t, _ = style_seq.shape
            pos = torch.arange(t, device=style_seq.device).unsqueeze(0).expand(b, t)
            h = self.input_proj(style_seq) + self.pos_emb(pos)
            enc = self.style_encoder(h, src_key_padding_mask=style_pad_mask)
            if style_pad_mask is not None:
                valid = (~style_pad_mask).unsqueeze(-1).float()
                pooled = (enc * valid).sum(dim=1) / valid.sum(dim=1).clamp(min=1.0)
            else:
                pooled = enc.mean(dim=1)
            return self.style_head(pooled)

        def forward(
            self,
            content_seq: Any,
            style_seq: Any,
            target_in_seq: Any,
            *,
            z: Any | None = None,
            content_pad_mask: Any | None = None,
            style_pad_mask: Any | None = None,
            target_pad_mask: Any | None = None,
        ) -> tuple[Any, Any]:
            b, tc, _ = content_seq.shape
            _, tt, _ = target_in_seq.shape
            device = content_seq.device

            pos_c = torch.arange(tc, device=device).unsqueeze(0).expand(b, tc)
            c_mem = self.content_encoder(
                self.content_proj(content_seq) + self.pos_emb(pos_c),
                src_key_padding_mask=content_pad_mask,
            )
            s_vec = self.encode_style(style_seq, style_pad_mask=style_pad_mask)
            if z is None:
                z = torch.zeros(b, self.cfg.latent_dim, device=device)
            cond_tok = self.cond_proj(torch.cat([s_vec, z], dim=-1)).unsqueeze(1)
            memory = torch.cat([cond_tok, c_mem], dim=1)

            if content_pad_mask is not None:
                zeros = torch.zeros((b, 1), dtype=torch.bool, device=device)
                mem_mask = torch.cat([zeros, content_pad_mask], dim=1)
            else:
                mem_mask = None

            pos_t = torch.arange(tt, device=device).unsqueeze(0).expand(b, tt)
            tgt = self.input_proj(target_in_seq) + self.pos_emb(pos_t)
            causal = nn.Transformer.generate_square_subsequent_mask(tt, device=device)
            dec_out = self.decoder(
                tgt,
                memory,
                tgt_mask=causal,
                tgt_key_padding_mask=target_pad_mask,
                memory_key_padding_mask=mem_mask,
            )
            pred_delta = self.delta_head(dec_out)
            pred_state_logits = self.state_head(dec_out)
            return pred_delta, pred_state_logits

        def freeze_base_enable_lora(self) -> int:
            """Freeze pretrained backbone weights and train only LoRA `(lora_a, lora_b)` parameters."""
            trainable = 0
            for name, param in self.named_parameters():
                is_lora = "lora_a" in name or "lora_b" in name
                param.requires_grad = is_lora
                if is_lora:
                    trainable += param.numel()
            return trainable

    return SDTTrajectoryModel(config)


class SDTTrainer:
    """High-level Colab GPU training, LoRA fine-tuning, and inference pipeline for SDT."""

    def __init__(self, cfg: SDTConfig | None = None, model: Any | None = None) -> None:
        self.torch = _require_torch()
        self.cfg = cfg or SDTConfig()
        if self.cfg.device == "auto":
            self.device = self.torch.device("cuda" if self.torch.cuda.is_available() else "cpu")
        else:
            self.device = self.torch.device(self.cfg.device)
        self.model = (model if model is not None else build_sdt_model(self.cfg)).to(self.device)

    def _pad_batch(self, seqs: Sequence[np.ndarray]) -> tuple[Any, Any]:
        max_len = min(self.cfg.max_seq_len, max(len(s) for s in seqs))
        b = len(seqs)
        tensor = self.torch.zeros((b, max_len, 5), dtype=self.torch.float32, device=self.device)
        pad_mask = self.torch.ones((b, max_len), dtype=self.torch.bool, device=self.device)
        for i, seq in enumerate(seqs):
            n = min(max_len, len(seq))
            tensor[i, :n] = self.torch.from_numpy(seq[:n]).to(self.device)
            pad_mask[i, :n] = False
        return tensor, pad_mask

    def fit(
        self,
        pairs: Sequence[tuple[Sequence[np.ndarray], Sequence[np.ndarray]]],
        *,
        lora_only: bool = True,
        epochs: int | None = None,
    ) -> dict[str, list[float]]:
        """Fine-tune SDT on `(content_strokes, writer_strokes)` pairs."""
        torch = self.torch
        F = torch.nn.functional
        if lora_only:
            self.model.freeze_base_enable_lora()

        params = [p for p in self.model.parameters() if p.requires_grad]
        opt = torch.optim.AdamW(params, lr=self.cfg.lr, weight_decay=self.cfg.weight_decay)

        encoded = [
            (strokes_to_delta_seq(c_s), strokes_to_delta_seq(w_s))
            for c_s, w_s in pairs
            if c_s and w_s
        ]
        if not encoded:
            raise ValueError("No valid (content_strokes, writer_strokes) training pairs provided.")

        n_epochs = epochs if epochs is not None else self.cfg.epochs
        history: dict[str, list[float]] = {"loss": [], "delta_loss": [], "state_loss": []}
        rng = np.random.default_rng(42)

        self.model.train()
        for _ep in range(n_epochs):
            order = rng.permutation(len(encoded))
            ep_loss = ep_delta = ep_state = 0.0
            steps = 0
            for start in range(0, len(order), self.cfg.batch_size):
                idx = order[start : start + self.cfg.batch_size]
                c_seqs = [encoded[i][0] for i in idx]
                t_seqs = [encoded[i][1] for i in idx]
                # Style reference sampled from other glyphs of the same writer in batch
                s_seqs = [encoded[int(order[(start + k + 1) % len(order)])][1] for k in range(len(idx))]

                c_ten, c_mask = self._pad_batch(c_seqs)
                s_ten, s_mask = self._pad_batch(s_seqs)
                t_ten, t_mask = self._pad_batch(t_seqs)

                # Shift target right by 1 step (BOS = [0, 0, 1, 0, 0])
                bos = torch.zeros((len(idx), 1, 5), dtype=torch.float32, device=self.device)
                bos[:, :, 2] = 1.0
                t_in = torch.cat([bos, t_ten[:, :-1, :]], dim=1)

                pred_delta, pred_state = self.model(
                    c_ten, s_ten, t_in,
                    content_pad_mask=c_mask,
                    style_pad_mask=s_mask,
                    target_pad_mask=t_mask,
                )

                valid = ~t_mask
                delta_loss = F.smooth_l1_loss(pred_delta[valid], t_ten[:, :, :2][valid])
                target_cls = torch.argmax(t_ten[:, :, 2:5], dim=-1)
                state_loss = F.cross_entropy(pred_state[valid], target_cls[valid])
                loss = 5.0 * delta_loss + state_loss

                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, self.cfg.grad_clip)
                opt.step()

                ep_loss += float(loss.item())
                ep_delta += float(delta_loss.item())
                ep_state += float(state_loss.item())
                steps += 1

            history["loss"].append(ep_loss / max(1, steps))
            history["delta_loss"].append(ep_delta / max(1, steps))
            history["state_loss"].append(ep_state / max(1, steps))
        return history

    def generate_variants(
        self,
        content_strokes: Sequence[np.ndarray],
        style_reference_strokes: Sequence[np.ndarray],
        *,
        n_variants: int = 4,
        temperature: float = 0.8,
        max_steps: int = 200,
        seed: int = 42,
    ) -> list[list[np.ndarray]]:
        """Autoregressively sample `n_variants` trajectories for a target character."""
        torch = self.torch
        torch.manual_seed(seed)
        np_rng = np.random.default_rng(seed)
        self.model.eval()

        c_seq = strokes_to_delta_seq(content_strokes)
        s_seq = strokes_to_delta_seq(style_reference_strokes)
        c_ten, c_mask = self._pad_batch([c_seq])
        s_ten, s_mask = self._pad_batch([s_seq])

        outputs: list[list[np.ndarray]] = []
        with torch.no_grad():
            for _ in range(n_variants):
                z = torch.randn((1, self.cfg.latent_dim), device=self.device) * temperature
                cur = torch.zeros((1, 1, 5), dtype=torch.float32, device=self.device)
                cur[:, :, 2] = 1.0
                generated_rows: list[np.ndarray] = []

                for _step in range(min(max_steps, self.cfg.max_seq_len - 1)):
                    pred_delta, pred_state = self.model(
                        c_ten, s_ten, cur, z=z, content_pad_mask=c_mask, style_pad_mask=s_mask
                    )
                    d_xy = pred_delta[0, -1].cpu().numpy()
                    if temperature > 0:
                        d_xy = d_xy + np_rng.normal(0.0, 0.004 * temperature, size=2)
                    probs = torch.softmax(pred_state[0, -1] / max(0.1, temperature), dim=-1).cpu().numpy()
                    state_idx = int(np_rng.choice(3, p=probs))
                    one_hot = np.zeros(3, dtype=np.float32)
                    one_hot[state_idx] = 1.0
                    row = np.concatenate([d_xy.astype(np.float32), one_hot])
                    generated_rows.append(row)

                    nxt = torch.from_numpy(row).view(1, 1, 5).to(self.device)
                    cur = torch.cat([cur, nxt], dim=1)
                    if state_idx == 2:
                        break

                strokes = delta_seq_to_strokes(np.asarray(generated_rows, dtype=np.float32))
                if strokes:
                    outputs.append(strokes)
        return outputs

    def save_checkpoint(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.torch.save({"config": asdict(self.cfg), "state_dict": self.model.state_dict()}, out)
        return out

    @classmethod
    def load_checkpoint(cls, path: str | Path, device: str = "auto") -> SDTTrainer:
        torch = _require_torch()
        try:
            ckpt = torch.load(path, map_location="cpu", weights_only=True)
        except Exception:
            ckpt = torch.load(path, map_location="cpu", weights_only=False)
        cfg = SDTConfig(**ckpt["config"])
        cfg.device = device
        trainer = cls(cfg=cfg)
        trainer.model.load_state_dict(ckpt["state_dict"])
        return trainer
