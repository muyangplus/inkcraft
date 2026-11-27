"""Application configuration and workspace paths for handwrite."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


def _default_root_dir() -> Path:
    env_root = os.environ.get("HANDWRITE_ROOT_DIR")
    if env_root:
        return Path(env_root).expanduser().resolve()
    # backend/handwrite/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    """Runtime settings for the handwrite backend server."""

    root_dir: Path = field(default_factory=_default_root_dir)
    fonts_dir: Path | None = None
    data_dir: Path | None = None
    db_path: Path | None = None
    profiles_path: Path | None = None
    frontend_dist_dir: Path | None = None

    host: str = "127.0.0.1"
    port: int = 8765

    # MinerU pipeline settings (strictly avoiding vLLM/sglang on 12GB VRAM)
    mineru_backend: str = field(
        default_factory=lambda: os.environ.get("MINERU_BACKEND", "pipeline")
    )
    mineru_device_mode: str = field(
        default_factory=lambda: os.environ.get("MINERU_DEVICE_MODE", "cuda")
    )
    mineru_virtual_vram_size: int = field(
        default_factory=lambda: int(os.environ.get("MINERU_VIRTUAL_VRAM_SIZE", "8"))
    )
    mineru_model_source: str = field(
        default_factory=lambda: os.environ.get("MINERU_MODEL_SOURCE", "local")
    )
    mineru_chunk_pages: int = field(
        default_factory=lambda: int(os.environ.get("MINERU_CHUNK_PAGES", "10"))
    )
    mineru_max_dpi: int = field(
        default_factory=lambda: int(os.environ.get("MINERU_MAX_DPI", "200"))
    )
    mineru_python: str = field(
        default_factory=lambda: os.environ.get("HANDWRITE_MINERU_PYTHON", "")
    )

    mock_speed_multiplier: float = field(
        default_factory=lambda: float(os.environ.get("HANDWRITE_MOCK_SPEED", "10.0"))
    )

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir).expanduser().resolve()

        if self.fonts_dir is None:
            env_fonts = os.environ.get("HANDWRITE_FONTS_DIR")
            self.fonts_dir = (
                Path(env_fonts).expanduser().resolve()
                if env_fonts
                else self.root_dir / "fonts"
            )
        else:
            self.fonts_dir = Path(self.fonts_dir).expanduser().resolve()

        if self.data_dir is None:
            env_data = os.environ.get("HANDWRITE_DATA_DIR")
            self.data_dir = (
                Path(env_data).expanduser().resolve()
                if env_data
                else self.root_dir / "data"
            )
        else:
            self.data_dir = Path(self.data_dir).expanduser().resolve()

        if self.db_path is None:
            self.db_path = self.data_dir / "app.db"
        else:
            self.db_path = Path(self.db_path).expanduser().resolve()

        if self.profiles_path is None:
            self.profiles_path = self.root_dir / "config" / "default_profiles.json"
        else:
            self.profiles_path = Path(self.profiles_path).expanduser().resolve()

        if self.frontend_dist_dir is None:
            self.frontend_dist_dir = self.root_dir / "frontend" / "dist"
        else:
            self.frontend_dist_dir = Path(self.frontend_dist_dir).expanduser().resolve()

    # Uppercase aliases for convenience
    @property
    def ROOT_DIR(self) -> Path:
        return self.root_dir

    @property
    def FONTS_DIR(self) -> Path:
        assert self.fonts_dir is not None
        return self.fonts_dir

    @property
    def DATA_DIR(self) -> Path:
        assert self.data_dir is not None
        return self.data_dir

    @property
    def DB_PATH(self) -> Path:
        assert self.db_path is not None
        return self.db_path

    @property
    def PROFILES_PATH(self) -> Path:
        assert self.profiles_path is not None
        return self.profiles_path

    @property
    def FRONTEND_DIST_DIR(self) -> Path:
        assert self.frontend_dist_dir is not None
        return self.frontend_dist_dir

    @property
    def documents_dir(self) -> Path:
        return self.DATA_DIR / "documents"

    @property
    def layouts_dir(self) -> Path:
        return self.DATA_DIR / "layouts"

    @property
    def cache_dir(self) -> Path:
        return self.DATA_DIR / "cache" / "mineru"

    @property
    def logs_dir(self) -> Path:
        return self.DATA_DIR / "logs"

    def ensure_dirs(self) -> None:
        self.FONTS_DIR.mkdir(parents=True, exist_ok=True)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.layouts_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> Settings:
        host = os.environ.get("HANDWRITE_HOST", "127.0.0.1")
        port = int(os.environ.get("HANDWRITE_PORT", "8765"))
        return cls(host=host, port=port)
