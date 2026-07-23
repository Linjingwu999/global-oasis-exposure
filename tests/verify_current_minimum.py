from __future__ import annotations

import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def workbook_shape(path: Path) -> tuple[int, int]:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.find("m:sheets", namespace)
        sheet_count = 0 if sheets is None else len(list(sheets))
        formulas = 0
        for name in archive.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                formulas += len(root.findall(".//m:f", namespace))
    return sheet_count, formulas


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
    assert len(estimands) == 31 and len({row["fact_id"] for row in estimands}) == 31
    assert len(facts) == 39 and len({row["fact_id"] for row in facts}) == 39
    assert len(denominators) == 12
    assert len(crosswalk) == 117
    assert len({(row["old_OasisID"], row["new_OasisID"]) for row in crosswalk}) == 117
    workbook = ROOT / "data" / "source_data" / "Source_Data_3437.xlsx"
    sheet_count, formula_count = workbook_shape(workbook)
    assert sheet_count == 39 and formula_count == 0
    print("PASS: 3437 rows; 31 estimands; 39 facts; 12 denominator rows; 117 crosswalk rows; 39 Source Data sheets; 0 formulas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
