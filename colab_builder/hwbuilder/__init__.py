"""Google Colab & local CPU offline-to-online AI handwriting font builder (`hwbuilder`).

Provides the full pipeline from printable A4 handwriting collection sheets to verified
single-file `.hwfont` databases:
  1. `sheet_gen`: A4 collection sheet PDF/PNG + deterministic JSON manifest
  2. `segment`: Scan illumination normalization, drop-out grid filtering, fiducial alignment,
     adaptive binarization, glyph cropping, and interactive HTML QA review
  3. `skeleton_align`: Pure-NumPy Zhang-Suen thinning, spur pruning, TPS template-guided
     stroke-order recovery, heuristic tracing fallback, and 0..1000 resampling
  4. `model_sdt`: PyTorch Style-Disentangled Trajectory (SDT + LoRA) model (lazy torch import)
     plus CPU-runnable `LocalStyleTransferAugmentor`
  5. `qc_export`: Automated quality-control gate (Chamfer diversity, geometry sanity, optional
     OCR round-trip) and `.hwfont` export/verification via `hwfont_sdk`
"""

from __future__ import annotations

__version__ = "1.0.0"

from hwbuilder.local_runner import (
    LocalBuildConfig,
    LocalBuildResult,
    QUICK_CHARSET,
    package_colab_bundle,
    preset_charset,
    probe_capabilities,
    resolve_engine,
    run_local_font_build,
)
from hwbuilder.model_sdt import LocalStyleTransferAugmentor, WriterStyleProfile
from hwbuilder.qc_export import (
    ExportResult,
    GlyphQCResult,
    QCConfig,
    VariantCandidate,
    chamfer_distance,
    export_hwfont,
    export_hwfont_detailed,
    qc_char_variants,
    qc_variant,
    render_strokes_bitmap,
)
from hwbuilder.segment import (
    CroppedGlyph,
    SegmentConfig,
    export_review_html,
    segment_scan,
)
from hwbuilder.sheet_gen import (
    DEFAULT_CORE_CHARSET,
    SheetConfig,
    SheetManifest,
    generate_collection_sheets,
)
from hwbuilder.skeleton_align import (
    VectorizeConfig,
    VectorizeResult,
    vectorize_glyph,
    zhang_suen_thin,
)

__all__ = [
    "__version__",
    "DEFAULT_CORE_CHARSET",
    "SheetConfig",
    "SheetManifest",
    "generate_collection_sheets",
    "CroppedGlyph",
    "SegmentConfig",
    "segment_scan",
    "export_review_html",
    "VectorizeConfig",
    "VectorizeResult",
    "zhang_suen_thin",
    "vectorize_glyph",
    "QUICK_CHARSET",
    "LocalBuildConfig",
    "LocalBuildResult",
    "preset_charset",
    "probe_capabilities",
    "resolve_engine",
    "run_local_font_build",
    "package_colab_bundle",
    "WriterStyleProfile",
    "LocalStyleTransferAugmentor",
    "QCConfig",
    "VariantCandidate",
    "GlyphQCResult",
    "ExportResult",
    "chamfer_distance",
    "render_strokes_bitmap",
    "qc_variant",
    "qc_char_variants",
    "export_hwfont",
    "export_hwfont_detailed",
]
