import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
SEED_DIR = ROOT / "seeds"

EARLIEST_AWARD_DATE = "2006-01-01"
MIN_AMOUNT = 1.0
LARGE_AMOUNT = 1e10

# Year-on-year tripwire for total awarded value. Wide on purpose: it exists to
# catch gross loading errors, not to model procurement growth.
YOY_FIRST_YEAR = 2014
YOY_MIN_RATIO = 0.5
YOY_MAX_RATIO = 1.75
DUPLICATE_VALUE_SHARE_WARN = 0.10

# Bunching is measured at each amount in seeds/analysis_amounts.csv: awards
# within BAND_WIDTH below versus within BAND_WIDTH above. Amounts with no rule
# attached act as placebos, because awards cluster under any round number.
BAND_WIDTH = 0.10
MIN_BAND_AWARDS = 30
MIN_AGENCY_YEAR_AWARDS = 30
SAME_DAY_MIN_NOTICES = 3
# Same calendar months compared before and after the 2025 rule change.
RULE_CHANGE_MONTHS = (3, 8)
RULE_CHANGE_YEARS = (2024, 2025)

# Supplier matching level, see pw/matching.py. Chosen from measured precision.
MATCH_LEVEL = 3


@dataclass(frozen=True)
class Settings:
    raw_dir: Path
    build_dir: Path
    seed_dir: Path
    snapshot_date: str

    @property
    def warehouse(self) -> Path:
        return self.build_dir / "warehouse.duckdb"

    @property
    def site_data(self) -> Path:
        return Path(os.environ.get("PW_SITE_DATA", ROOT / "site" / "data"))


def load_manifest(seed_dir: Path = SEED_DIR) -> dict:
    return json.loads((seed_dir / "raw_manifest.json").read_text(encoding="utf-8"))


def default_settings() -> Settings:
    return Settings(
        raw_dir=Path(os.environ.get("PW_RAW_DIR", ROOT / "data" / "raw")),
        build_dir=Path(os.environ.get("PW_BUILD_DIR", ROOT / "build")),
        seed_dir=SEED_DIR,
        snapshot_date=load_manifest()["snapshot_date"],
    )
