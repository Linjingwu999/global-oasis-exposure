from __future__ import annotations

import csv
import importlib.util
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_IDS = {
    "ASTJ10032",
    "ASTR04013",
    "ASTR08004",
    "ASTR08020",
    "ASTR08029",
    "ASTR08036",
}

# Point estimates are exact arithmetic on the shipped table; the only expected
# difference is floating-point summation order.
POINT_TOLERANCE = 1e-9


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load(module_name: str, relative: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def check_inputs() -> list[dict[str, str]]:
    data = rows(ROOT / "data" / "analysis_input_minimal.csv")
    ids = [row["OasisID"] for row in data]
    assert len(data) == 3437, f"expected 3437 rows, got {len(data)}"
    assert len(set(ids)) == 3437, "OasisID is not unique"
    assert not set(ids).intersection(EXCLUDED_IDS), "an excluded identifier is present"

    estimands = rows(ROOT / "data" / "primary_estimands_31.csv")
    assert len(estimands) == 31, f"expected 31 estimand records, got {len(estimands)}"
    assert len({row["fact_id"] for row in estimands}) == 31, "fact_id is not unique"
    return estimands


def check_estimands_recompute(ledger: list[dict[str, str]]) -> int:
    """Recompute all 31 point estimands from the shipped table and compare.

    The previous version of this test asserted only row counts, so ten of the
    thirty-one estimands could fail to compute without the test noticing.
    """
    import pandas as pd

    estimands_mod = _load("release_estimands", "code/core/estimands.py")

    data = pd.read_csv(ROOT / "data" / "analysis_input_minimal.csv", low_memory=False)
    contract = pd.read_csv(ROOT / "config" / "estimands_31.csv")
    assert len(contract) == 31, f"contract has {len(contract)} rows, expected 31"

    # strict=True (the default): any estimand that cannot be computed raises here.
    computed, failures = estimands_mod.compute_point_estimands(data, contract)
    assert not failures, f"unexpected failures: {failures}"
    assert len(computed) == 31, f"computed {len(computed)} estimands, expected 31"

    locked = {row["fact_id"]: row for row in ledger}
    computed_records = computed.to_dict("records")
    contract_records = contract.to_dict("records")
    assert len(computed_records) == len(contract_records)

    mismatches: list[str] = []
    compared = 0
    for contract_row, result in zip(contract_records, computed_records):
        fact_id = str(contract_row.get("fact_id", ""))
        if fact_id not in locked:
            mismatches.append(f"{fact_id}: not present in primary_estimands_31.csv")
            continue
        expected_raw = locked[fact_id].get("effect_bwh_minus_bwk", "")
        actual = result.get("effect_bwh_minus_bwk")
        if expected_raw in ("", None) or actual is None:
            mismatches.append(f"{fact_id}: missing effect value")
            continue
        expected = float(expected_raw)
        if not math.isfinite(float(actual)):
            mismatches.append(f"{fact_id}: recomputed effect is not finite")
            continue
        delta = abs(float(actual) - expected)
        scale = max(1.0, abs(expected))
        if delta / scale > POINT_TOLERANCE:
            mismatches.append(
                f"{fact_id}: recomputed {actual!r} vs locked {expected!r} (delta {delta:g})"
            )
        compared += 1

    assert not mismatches, "point estimates do not reproduce -> " + "; ".join(mismatches)
    return compared


def main() -> int:
    ledger = check_inputs()
    compared = check_estimands_recompute(ledger)
    print(
        "PASS: 3437 rows; 31 primary estimand records; "
        f"{compared}/31 point estimates recomputed and matched "
        f"to <= {POINT_TOLERANCE:g} relative"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
