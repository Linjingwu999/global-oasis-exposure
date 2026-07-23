from __future__ import annotations

import pandas as pd


def classify_locked_support(row: pd.Series) -> str:
    ci_low = float(row["ci95_low"])
    ci_high = float(row["ci95_high"])
    q_value = float(row["fdr_q"])
    if not (ci_low > 0 or ci_high < 0) or q_value >= 0.05:
        return "not_supported"
    summary = str(row["sensitivity_summary"])
    if "direction_agrees=False" in summary or "support_agrees=False" in summary:
        return "sensitive"
    return "robust"


def validate_locked_sensitivity(primary: pd.DataFrame) -> dict[str, object]:
    summaries = primary["sensitivity_summary"].fillna("").astype(str)
    has_250 = summaries.str.contains("250 km", regex=False)
    has_1000 = summaries.str.contains("1000 km", regex=False)
    if not bool((has_250 & has_1000).all()):
        missing = primary.loc[~(has_250 & has_1000), "fact_id"].astype(str).tolist()
        raise ValueError(f"Locked spatial-scale sensitivity missing for {missing}")
    classified = primary.apply(classify_locked_support, axis=1)
    changed = primary.loc[classified.ne(primary["support_class"]), "fact_id"].astype(str).tolist()
    if changed:
        raise ValueError(f"Support classification rule mismatch for {changed}")
    return {
        "estimands_with_250km_record": int(has_250.sum()),
        "estimands_with_1000km_record": int(has_1000.sum()),
        "support_rule_reproduced": True,
        "mode": "locked_output_verification",
    }


def futurepop_accounting(data: pd.DataFrame) -> dict[str, int]:
    coverage = pd.to_numeric(data["futurepop_coverage"], errors="coerce")
    return {
        "coverage_gt0": int((coverage > 0).sum()),
        "coverage_ge050": int((coverage >= 0.5).sum()),
        "no_valid": int((coverage <= 0).sum()),
    }
