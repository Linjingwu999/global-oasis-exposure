from __future__ import annotations

import math
from typing import Mapping

import numpy as np
import pandas as pd


STRICT_CLASSES = ("BWh oases", "BWk oases")


def q_pass(series: pd.Series) -> pd.Series:
    return series.astype("string").str.lower().str.startswith("pass", na=False)


def qa_field_for(source_field: str) -> str:
    if source_field.startswith(("pop_density_", "built_s_")):
        return "ghsl_qc"
    if source_field == "ai_scaled":
        return "ai_qc"
    if source_field.startswith("terraclimate_"):
        return "terraclimate_qc"
    if source_field == "ever_water_fraction":
        return "jrc_qc"
    if source_field.startswith("utci_"):
        return "utci_qc"
    if source_field.startswith("nex_"):
        return "nex_qc"
    raise ValueError(f"No QA field is registered for {source_field}")


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(valid):
        return float("nan")
    clean_values = values[valid]
    clean_weights = weights[valid]
    order = np.argsort(clean_values, kind="mergesort")
    clean_values = clean_values[order]
    clean_weights = clean_weights[order]
    threshold = clean_weights.sum() / 2.0
    index = int(np.searchsorted(np.cumsum(clean_weights), threshold, side="left"))
    return float(clean_values[min(index, len(clean_values) - 1)])


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(valid):
        return float("nan")
    total = float(weights[valid].sum())
    return float(np.dot(values[valid], weights[valid]) / total)


def method_weights(frame: pd.DataFrame, method: str) -> np.ndarray:
    if method in ("median_log_ratio", "median_difference"):
        return np.ones(len(frame), dtype=float)
    if method == "area_weighted_mean_difference":
        return pd.to_numeric(frame["area_km2"], errors="coerce").to_numpy(float)
    if method == "population_weighted_mean_difference":
        return pd.to_numeric(frame["pop_2020_ghsl"], errors="coerce").to_numpy(float)
    raise ValueError(f"Unsupported implementation method: {method}")


def group_statistic(
    values: np.ndarray,
    groups: np.ndarray,
    method: str,
    weights: np.ndarray,
) -> tuple[float, float, float, float | None]:
    hot_mask = groups == STRICT_CLASSES[0]
    cold_mask = groups == STRICT_CLASSES[1]
    if method == "median_log_ratio":
        hot = weighted_median(values[hot_mask], weights[hot_mask])
        cold = weighted_median(values[cold_mask], weights[cold_mask])
        if not (np.isfinite(hot) and np.isfinite(cold) and hot > 0 and cold > 0):
            return float("nan"), hot, cold, None
        effect = float(math.log(hot / cold))
        return effect, hot, cold, float(math.exp(effect))
    if method == "median_difference":
        hot = weighted_median(values[hot_mask], weights[hot_mask])
        cold = weighted_median(values[cold_mask], weights[cold_mask])
    elif method in (
        "area_weighted_mean_difference",
        "population_weighted_mean_difference",
    ):
        hot = weighted_mean(values[hot_mask], weights[hot_mask])
        cold = weighted_mean(values[cold_mask], weights[cold_mask])
    else:
        raise ValueError(f"Unsupported implementation method: {method}")
    if not (np.isfinite(hot) and np.isfinite(cold)):
        return float("nan"), hot, cold, None
    return float(hot - cold), hot, cold, None


def sample_for_estimand(
    data: pd.DataFrame,
    contract_row: Mapping[str, object],
    *,
    scale_km: int = 500,
    polygon_only: bool = False,
    remove_top_one_percent_area: bool = False,
) -> pd.DataFrame:
    source_field = str(contract_row["source_field"])
    method = str(contract_row["implementation_method"])
    qa_field = qa_field_for(source_field)
    required = {
        "class_label_en",
        source_field,
        qa_field,
        f"block_{scale_km}km",
        "area_km2",
    }
    if method == "population_weighted_mean_difference":
        required.add("pop_2020_ghsl")
    missing = sorted(required - set(data.columns))
    if missing:
        raise KeyError(f"Missing input fields: {missing}")

    values = pd.to_numeric(data[source_field], errors="coerce")
    mask = data["class_label_en"].isin(STRICT_CLASSES)
    mask &= values.notna()
    mask &= q_pass(data[qa_field])
    if method == "population_weighted_mean_difference":
        population = pd.to_numeric(data["pop_2020_ghsl"], errors="coerce")
        mask &= population.notna() & (population >= 0)
    if polygon_only:
        mask &= data["nex_method"].astype("string").eq("polygon_reducer")
    sample = data.loc[mask].copy()
    if remove_top_one_percent_area:
        remove_count = max(1, int(math.ceil(len(sample) * 0.01)))
        sample = sample.drop(sample.nlargest(remove_count, "area_km2").index)
    if sample.empty:
        raise ValueError(f"No valid rows for {contract_row['estimand']}")
    for label in STRICT_CLASSES:
        if not sample["class_label_en"].eq(label).any():
            raise ValueError(f"No valid {label} rows for {contract_row['estimand']}")
    if sample[f"block_{scale_km}km"].isna().any():
        raise ValueError(f"Missing {scale_km}-km block identifiers")
    return sample


def point_result(sample: pd.DataFrame, contract_row: Mapping[str, object]) -> dict[str, object]:
    source_field = str(contract_row["source_field"])
    method = str(contract_row["implementation_method"])
    values = pd.to_numeric(sample[source_field], errors="coerce").to_numpy(float)
    groups = sample["class_label_en"].astype(str).to_numpy()
    weights = method_weights(sample, method)
    effect, hot, cold, ratio = group_statistic(values, groups, method, weights)
    return {
        "fact_id": str(contract_row["fact_id"]),
        "domain": str(contract_row["domain"]),
        "estimand": str(contract_row["estimand"]),
        "implementation_method": method,
        "n_bwh": int(np.count_nonzero(groups == STRICT_CLASSES[0])),
        "n_bwk": int(np.count_nonzero(groups == STRICT_CLASSES[1])),
        "estimate_bwh": hot,
        "estimate_bwk": cold,
        "effect_bwh_minus_bwk": effect,
        "effect_ratio_bwh_over_bwk": ratio,
    }


def compute_point_estimands(
    data: pd.DataFrame, contract: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for row in contract.to_dict("records"):
        try:
            sample = sample_for_estimand(data, row)
            results.append(point_result(sample, row))
        except Exception as exc:
            failures.append({"estimand": str(row.get("estimand", "")), "error": str(exc)})
    return pd.DataFrame(results), failures
