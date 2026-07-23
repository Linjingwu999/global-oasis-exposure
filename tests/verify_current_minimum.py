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
    facts = rows(ROOT / "data" / "master_numeric_facts_39.csv")
    denominators = rows(ROOT / "data" / "denominator_contract.csv")
    crosswalk = rows(ROOT / "data" / "oasis_id_crosswalk_117.csv")
    mapping = rows(ROOT / "data" / "figure_source_data_mapping.csv")
    assert len(estimands) == 31 and len({row["fact_id"] for row in estimands}) == 31
    assert len(facts) == 39 and len({row["fact_id"] for row in facts}) == 39
    assert len(denominators) == 12
    assert len(crosswalk) == 117
    assert len({(row["old_OasisID"], row["new_OasisID"]) for row in crosswalk}) == 117
    assert {row["figure_id"] for row in mapping} == {f"Figure {i}" for i in range(1, 9)}
    assert all((ROOT / "data" / "figures" / name).is_file() for name in ["Figure5_plot_data.csv", "Figure6_A_Centroids.csv", "Figure6_A_Points.csv", "Figure6_B_Thresholds.csv", "Figure6_C_IQR.csv"])
    print("PASS: 3437 rows; 31 estimands; 39 facts; 12 denominator rows; 117 crosswalk rows; 8 figure mappings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
