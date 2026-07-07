"""Central runtime configuration, driven by environment variables.

Everything has a sane local default so the whole Phase 0 pipeline runs
offline from parquet files without any secrets configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    # Local data lake layout (all gitignored):
    #   data/raw/fastf1/...    raw FastF1 parquet dumps
    #   data/raw/openf1/...    raw OpenF1 JSON/parquet dumps
    #   data/normalized/...    internal-schema parquet tables
    #   data/snapshots/...     sim_snapshots per session (backtest output)
    #   data/models/...        fitted model parameters (JSON)
    data_dir: Path = field(default_factory=lambda: _env_path("APEXODDS_DATA_DIR", "data"))
    fastf1_cache_dir: Path = field(
        default_factory=lambda: _env_path("APEXODDS_FASTF1_CACHE", "data/fastf1_cache")
    )

    openf1_base_url: str = field(
        default_factory=lambda: os.environ.get("OPENF1_BASE_URL", "https://api.openf1.org/v1")
    )
    # Free-tier limits per OpenF1 docs: 3 req/s and 30 req/min.
    openf1_max_per_second: int = 3
    openf1_max_per_minute: int = 30

    jolpica_base_url: str = field(
        default_factory=lambda: os.environ.get("JOLPICA_BASE_URL", "https://api.jolpi.ca/ergast/f1")
    )

    # Postgres URI of the Supabase project ("Connection string" in dashboard),
    # e.g. postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres
    supabase_db_url: str | None = field(
        default_factory=lambda: os.environ.get("SUPABASE_DB_URL") or None
    )

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def normalized_dir(self) -> Path:
        return self.data_dir / "normalized"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def reports_dir(self) -> Path:
        return Path(os.environ.get("APEXODDS_REPORTS_DIR", "reports"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
