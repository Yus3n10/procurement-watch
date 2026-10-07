import shutil
from pathlib import Path

import duckdb
import pytest

from pw import config

SEEDS = Path(__file__).resolve().parent.parent / "seeds"

GOOD = {
    "reference_id": "100",
    "contract_no": "100",
    "award_title": "Office supplies",
    "notice_title": "Supply and delivery of office supplies",
    "awardee_name": "ABC TRADING",
    "organization_name": "CITY OF TALISAY",
    "area_of_delivery": "Negros Occidental",
    "business_category": "Office Supplies and Devices",
    "contract_amount": 50000.0,
    "award_date": "2024-03-01",
    "award_status": "active",
}


def award(n: int, **overrides) -> dict:
    """A valid award row with a deterministic id, overridden per test."""
    return {"id": f"00000000-0000-0000-0000-{n:012d}", **GOOD, **overrides}


@pytest.fixture
def make_settings(tmp_path):
    def _make(rows: list[dict], allowlist: list[str] = ()) -> config.Settings:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(exist_ok=True)
        seed_dir = tmp_path / "seeds"
        if seed_dir.exists():
            shutil.rmtree(seed_dir)
        shutil.copytree(SEEDS, seed_dir)
        if allowlist:
            lines = ["award_id,reviewed_on,evidence"] + [f"{a},2026-01-01,test" for a in allowlist]
            (seed_dir / "large_amount_allowlist.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

        con = duckdb.connect()
        con.execute(
            """
            create table t (
                id uuid, reference_id varchar, contract_no varchar, award_title varchar,
                notice_title varchar, awardee_name varchar, organization_name varchar,
                area_of_delivery varchar, business_category varchar, contract_amount double,
                award_date timestamp, award_status varchar
            )
            """
        )
        columns = [
            "id", "reference_id", "contract_no", "award_title", "notice_title", "awardee_name",
            "organization_name", "area_of_delivery", "business_category", "contract_amount",
            "award_date", "award_status",
        ]
        con.executemany(
            "insert into t values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [[row[c] for c in columns] for row in rows],
        )
        target = str(raw_dir / "philgeps.parquet").replace("\\", "/")
        con.execute(f"copy t to '{target}' (format parquet)")
        con.close()
        return config.Settings(
            raw_dir=raw_dir,
            build_dir=tmp_path / "build",
            seed_dir=seed_dir,
            snapshot_date="2026-01-06",
        )

    return _make
