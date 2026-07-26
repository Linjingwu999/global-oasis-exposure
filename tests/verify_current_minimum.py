from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    data = rows(ROOT / "data" / "analysis_input_minimal.csv")
    ids = [row["OasisID"] for row in data]
    assert len(data) == 3437
    assert len(set(ids)) == 3437
    assert not set(ids).intersection({"ASTJ10032", "ASTR04013", "ASTR08004", "ASTR08020", "ASTR08029", "ASTR08036"})
    estimands = rows(ROOT / "data" / "primary_estimands_31.csv")
    assert len(estimands) == 31 and len({row["fact_id"] for row in estimands}) == 31
    print("PASS: 3437 rows; 31 primary estimand records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
