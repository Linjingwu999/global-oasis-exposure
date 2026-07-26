#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the Source Data workbook for the 3,437-oasis global oasis exposure analysis.

The workbook is regenerated from scratch on every run. No value is carried over
from any earlier workbook version, and no numeric value is hard-coded in this
script: every number written to a data sheet is read from, or computed from, one
of the authoritative inputs listed in ``INPUTS`` below. Only descriptive prose
(README text, Data_Dictionary definitions, module labels) is authored here, and
that prose is written so that it states no numbers of its own -- counts and
denominators quoted in the README sheet are interpolated at build time from the
data.

Authoritative inputs
--------------------
Repository (public release):
    data/analysis_input_minimal.csv          3,437 rows x 219 columns
    data/primary_estimands_31.csv            31 primary estimand records
    data/data_dictionary.csv                 released-field dictionary
    data/source_product_manifest_current.csv source-product manifest
    data/third_party_product_boundary.csv    redistribution boundary
    config/estimands_31.csv                  estimand definitions
    config/analysis.yml                      analysis design constants

Sensitivity evidence pack (outside the repository, read-only):
    T9_scale_250_1000_locked_vs_reproduced.csv   locked 250/1,000 km intervals
    T1_effective_n_per_estimand.csv              cross-check only (optional)
    T2_spatial_block_counts.csv                  cross-check only (optional)
    T3_futurepop_coverage_by_class.csv           cross-check only (optional)
    S3b_six_excluded_oases.csv                   exclusion record for the README

The evidence pack is not redistributed with this repository and its location is
not recorded here. Supply it with --evidence-dir or the environment variable
OASIS_SENSITIVITY_EVIDENCE_DIR.

Usage
-----
    python scripts/build_source_data_workbook.py --evidence-dir <path>
    python scripts/build_source_data_workbook.py --evidence-dir <path> --out <path>
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "data" / "Source_Data_CEE_v1.xlsx"

# The sensitivity evidence pack is not part of this release and no local
# filesystem path to it is stored in this repository. Supply its location with
# --evidence-dir, or via the environment variable below.
EVIDENCE_DIR_ENV = "OASIS_SENSITIVITY_EVIDENCE_DIR"

# --------------------------------------------------------------------------
# Structural constants (labels and rules only -- never numeric results)
# --------------------------------------------------------------------------

AREA_BIN_EDGES = [-np.inf, 10.0, 100.0, 1000.0, 10000.0, np.inf]
AREA_BIN_LABELS = ["1-10", "10-100", "100-1,000", "1,000-10,000", ">=10,000"]

UTCI_HEAT_FIELDS = OrderedDict(
    [
        (">=32C", "utci_mean_annual_days_max_ge_32c"),
        (">=38C", "utci_mean_annual_days_max_ge_38c"),
        (">=46C", "utci_mean_annual_days_max_ge_46c"),
    ]
)
UTCI_COLD_FIELDS = OrderedDict(
    [
        ("<=-13C", "utci_mean_annual_days_min_le_minus13c"),
        ("<=-27C", "utci_mean_annual_days_min_le_minus27c"),
        ("<=-40C", "utci_mean_annual_days_min_le_minus40c"),
    ]
)

NEX_SCENARIOS = ["ssp245", "ssp585"]
NEX_WINDOWS = ["2041_2070", "2071_2099"]
NEX_VARIABLES = ["tasmax", "tasmin", "pr"]

# Figure8_Summary reports one scenario-window combination. The choice is
# recorded explicitly in the sheet so it can never again be silent.
FIG8_SCENARIO = "ssp585"
FIG8_WINDOW = "2071_2099"

# source_field prefix -> module QC gate column. Structural routing, not data.
QA_GATE_RULES = [
    ("pop_density_per_km2_polygon_area", "ghsl_qc"),
    ("built_s_share_of_polygon_area", "ghsl_qc"),
    ("ai_scaled", "ai_qc"),
    ("et0_", "et0_qc"),
    ("terraclimate_", "terraclimate_qc"),
    ("ever_water_fraction", "jrc_qc"),
    ("utci_", "utci_qc"),
    ("nex_", "nex_qc"),
    ("pop_ssp", "none"),
    ("gdp2020_", "gdp_qc"),
    ("viirs2020_", "viirs_qc"),
]

NE_POLICY = (
    "Blank means the value is not estimable under the stated module validity "
    "rule. Blank is never zero; an explicit 0 is a measured zero."
)
NE_IDENTITY = "Never blank; present for every oasis in the analysis population."


def qa_gate_for(source_field: str) -> str:
    for prefix, gate in QA_GATE_RULES:
        if source_field.startswith(prefix):
            return gate
    raise KeyError(f"no QA gate rule for source field {source_field!r}")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def read_csv_any(path: Path, **kw) -> pd.DataFrame:
    """Read a CSV, tolerating the mixed encodings present in the evidence pack."""
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("could not decode", b"", 0, 1, str(path))


def read_analysis_yml(path: Path) -> dict:
    """Minimal flat/list YAML reader so the build has no extra dependency."""
    cfg: dict = {}
    key = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.lstrip().startswith("- "):
            if key is not None:
                cfg.setdefault(key, [])
                if isinstance(cfg[key], list):
                    cfg[key].append(raw.split("- ", 1)[1].strip())
            continue
        name, _, value = raw.partition(":")
        key = name.strip()
        value = value.strip()
        cfg[key] = value if value else []
    return cfg


# --------------------------------------------------------------------------
# Shared derivations
# --------------------------------------------------------------------------


def class_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Deterministic class key table: exact_background_class -> class_label_en."""
    pairs = (
        df[["exact_background_class", "class_label_en"]]
        .drop_duplicates()
        .sort_values("exact_background_class")
        .reset_index(drop=True)
    )
    if len(pairs) != df["exact_background_class"].nunique():
        raise AssertionError("exact_background_class does not map 1:1 to class_label_en")
    return pairs


def continent_order(df: pd.DataFrame) -> list:
    counts = df["continent5"].value_counts()
    return list(counts.sort_values(ascending=False, kind="mergesort").index)


def area_bin(series: pd.Series) -> pd.Series:
    return pd.cut(series, bins=AREA_BIN_EDGES, labels=AREA_BIN_LABELS, right=False)


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna()
    if not mask.any():
        return float("nan")
    return float(np.average(values[mask].to_numpy(), weights=weights[mask].to_numpy()))


# The patch-median estimator of the primary analysis uses the LOWER order
# statistic, i.e. for an even class size it takes the lower of the two central
# values rather than their average. This is verified at build time against
# estimate_bwh / estimate_bwk of data/primary_estimands_31.csv. Descriptive
# figure statistics elsewhere in this workbook use the ordinary
# linear-interpolation median; the two definitions are never mixed within a
# sheet, and every column that uses the estimator definition says so.
ESTIMAND_MEDIAN_DEFINITION = (
    "lower order statistic (numpy percentile method='lower'); matches the "
    "patch-median estimator behind Table2_Estimands"
)


def estimand_median(values: pd.Series) -> float:
    v = values.dropna().to_numpy(dtype=float)
    if v.size == 0:
        return float("nan")
    return float(np.percentile(v, 50, method="lower"))


# --------------------------------------------------------------------------
# Sheet builders
# --------------------------------------------------------------------------


def build_figure2_polygon(df):
    out = pd.DataFrame(
        {
            "OasisID": df["OasisID"],
            "continent": df["continent5"],
            "exact_background_class": df["exact_background_class"],
            "background_class": df["class_label_en"],
            "polygon_area_km2": df["polygon_area_km2_geodesic"],
        }
    )
    return out.reset_index(drop=True)


def build_figure2_summary(df, classes):
    g = df.groupby("exact_background_class", observed=True)
    out = pd.DataFrame(
        {
            "exact_background_class": classes["exact_background_class"],
            "background_class": classes["class_label_en"],
        }
    )
    out["feature_count"] = out["exact_background_class"].map(g.size())
    out["polygon_area_km2_geodesic"] = out["exact_background_class"].map(
        g["polygon_area_km2_geodesic"].sum()
    )
    out["area_million_km2"] = out["polygon_area_km2_geodesic"] / 1e6
    return out[
        [
            "exact_background_class",
            "background_class",
            "feature_count",
            "polygon_area_km2_geodesic",
            "area_million_km2",
        ]
    ]


def build_figure3_polygon(df):
    return build_figure2_polygon(df)


def build_figure3_classsummary(df, classes):
    total_area = df["polygon_area_km2_geodesic"].sum()
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        a = sub["polygon_area_km2_geodesic"].to_numpy(dtype=float)
        class_area = float(a.sum())
        small = a[a < 100.0]
        rows.append(
            {
                "exact_background_class": cls["exact_background_class"],
                "background_class": cls["class_label_en"],
                "feature_count": int(len(sub)),
                "area_km2": class_area,
                "area_share_pct": 100.0 * class_area / total_area,
                "mean_area_km2": float(a.mean()),
                "median_area_km2": float(np.median(a)),
                "p25_area_km2": float(np.percentile(a, 25)),
                "p75_area_km2": float(np.percentile(a, 75)),
                "p90_area_km2": float(np.percentile(a, 90)),
                "p95_area_km2": float(np.percentile(a, 95)),
                "p99_area_km2": float(np.percentile(a, 99)),
                "max_area_km2": float(a.max()),
                "count_lt_10_km2": int((a < 10.0).sum()),
                "count_lt_100_km2": int((a < 100.0).sum()),
                "area_lt_100_km2": float(small.sum()),
                "area_lt_100_share_of_class_pct": 100.0 * float(small.sum()) / class_area,
            }
        )
    return pd.DataFrame(rows)


def build_figure3_areabins(df, classes):
    total_area = df["polygon_area_km2_geodesic"].sum()
    work = df.assign(area_bin=area_bin(df["polygon_area_km2_geodesic"]))
    rows = []
    for label in AREA_BIN_LABELS:
        for _, cls in classes.iterrows():
            sub = work[
                (work["area_bin"] == label)
                & (work["exact_background_class"] == cls["exact_background_class"])
            ]
            area = float(sub["polygon_area_km2_geodesic"].sum())
            rows.append(
                {
                    "area_bin": label,
                    "exact_background_class": cls["exact_background_class"],
                    "background_class": cls["class_label_en"],
                    "feature_count": int(len(sub)),
                    "area_km2": area,
                    "area_share_of_global_pct": 100.0 * area / total_area,
                }
            )
    return pd.DataFrame(rows)


def build_figure4_polygon(df):
    out = build_figure2_polygon(df)
    out["ghsl_population_2020_persons"] = df["pop_sum_2020"].to_numpy()
    out["ghsl_population_density_persons_per_km2"] = df[
        "pop_density_per_km2_polygon_area"
    ].to_numpy()
    out["ghsl_built_up_area_2020_km2"] = df["built_s_sum_2020_km2"].to_numpy()
    out["ghsl_built_up_area_fraction"] = df["built_s_share_of_polygon_area"].to_numpy()
    return out


def build_figure4_summary(df, classes):
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        area = float(sub["polygon_area_km2_geodesic"].sum())
        pop = float(sub["pop_sum_2020"].sum())
        built = float(sub["built_s_sum_2020_km2"].sum())
        rows.append(
            {
                "exact_background_class": cls["exact_background_class"],
                "background_class": cls["class_label_en"],
                "feature_count": int(len(sub)),
                "polygon_area_km2": area,
                "population_2020": pop,
                "population_2020_million": pop / 1e6,
                "population_density_per_km2": pop / area,
                "built_up_2020_km2": built,
                "built_up_fraction_pct": 100.0 * built / area,
            }
        )
    return pd.DataFrame(rows)


def build_figure5_polygon(df):
    out = build_figure2_polygon(df)
    out["aridity_index"] = df["ai_scaled"].to_numpy()
    out["et0_mm_yr"] = df["et0_v31_yr_raw_area_weighted_mean_raw"].to_numpy()
    out["et0_sd_mm_yr"] = df["et0_v31_yr_sd_raw_area_weighted_mean_raw"].to_numpy()
    for f in [
        "terraclimate_ppt_1991_2020_mean_annual_mm",
        "terraclimate_pet_1991_2020_mean_annual_mm",
        "terraclimate_aet_1991_2020_mean_annual_mm",
        "terraclimate_def_1991_2020_mean_annual_mm",
        "terraclimate_soil_1991_2020_mean_monthly_mm",
        "terraclimate_ppt_minus_pet_1991_2020_mean_annual_mm",
        "occurrence_area_weighted_pct",
        "recurrence_area_weighted_pct",
    ]:
        out[f] = df[f].to_numpy()
    out["jrc_ever_water_area_km2"] = df["ever_water_area_m2"].to_numpy() / 1e6
    out["jrc_permanent_water_area_km2"] = df["permanent_water_area_m2"].to_numpy() / 1e6
    out["jrc_seasonal_water_area_km2"] = df["seasonal_water_area_m2"].to_numpy() / 1e6
    out["jrc_ever_water_fraction_pct"] = df["ever_water_fraction"].to_numpy() * 100.0
    out["jrc_permanent_water_fraction_pct"] = (
        df["permanent_water_fraction"].to_numpy() * 100.0
    )
    out["jrc_seasonal_water_fraction_pct"] = (
        df["seasonal_water_fraction"].to_numpy() * 100.0
    )
    return out


def build_figure5_classsummary(df, classes):
    """Per-class water and aridity summary.

    WEIGHTING IS DELIBERATELY MIXED and is declared per column by the
    ``weighting_scheme`` column: the Aridity Index, ET0, ET0-SD and every JRC
    field are AREA-WEIGHTED (weight = polygon_area_km2_geodesic); the five
    TerraClimate fields are UNWEIGHTED class means. Applying a single uniform
    rule silently corrupts one group or the other.
    """
    area_weighted_fields = OrderedDict(
        [
            ("aridity_index_scaled", "ai_scaled"),
            ("et0_mm_yr", "et0_v31_yr_raw_area_weighted_mean_raw"),
            ("et0_sd_mm_yr", "et0_v31_yr_sd_raw_area_weighted_mean_raw"),
        ]
    )
    unweighted_fields = [
        "terraclimate_ppt_1991_2020_mean_annual_mm",
        "terraclimate_pet_1991_2020_mean_annual_mm",
        "terraclimate_aet_1991_2020_mean_annual_mm",
        "terraclimate_def_1991_2020_mean_annual_mm",
        "terraclimate_soil_1991_2020_mean_monthly_mm",
        "terraclimate_ppt_minus_pet_1991_2020_mean_annual_mm",
    ]
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        w = sub["polygon_area_km2_geodesic"]
        rec = {
            "exact_background_class": cls["exact_background_class"],
            "background_class": cls["class_label_en"],
            "feature_count": int(len(sub)),
            "weighting_scheme": (
                "aridity_index/et0/et0_sd/jrc_* = area-weighted by "
                "polygon_area_km2_geodesic; terraclimate_* = unweighted class mean"
            ),
        }
        for out_name, field in area_weighted_fields.items():
            rec[out_name] = weighted_mean(sub[field], w)
        for field in unweighted_fields:
            rec[field] = float(sub[field].mean())
        rec["jrc_ever_water_fraction_pct"] = 100.0 * weighted_mean(
            sub["ever_water_fraction"], w
        )
        rec["jrc_permanent_water_fraction_pct"] = 100.0 * weighted_mean(
            sub["permanent_water_fraction"], w
        )
        rec["jrc_seasonal_water_fraction_pct"] = 100.0 * weighted_mean(
            sub["seasonal_water_fraction"], w
        )
        rec["jrc_occurrence_area_weighted_pct"] = weighted_mean(
            sub["occurrence_area_weighted_pct"], w
        )
        rec["jrc_recurrence_area_weighted_pct"] = weighted_mean(
            sub["recurrence_area_weighted_pct"], w
        )
        rec["jrc_ever_water_area_km2"] = float(sub["ever_water_area_m2"].sum()) / 1e6
        rec["jrc_permanent_water_area_km2"] = (
            float(sub["permanent_water_area_m2"].sum()) / 1e6
        )
        rec["jrc_seasonal_water_area_km2"] = (
            float(sub["seasonal_water_area_m2"].sum()) / 1e6
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def build_figure6_polygon(df):
    out = pd.DataFrame(
        {
            "OasisID": df["OasisID"],
            "continent": df["continent5"],
            "exact_background_class": df["exact_background_class"],
            "background_class": df["class_label_en"],
            "ghsl_population_2020_persons": df["pop_sum_2020"],
            "utci_qc": df["utci_qc"],
            "utci_denominator_method": df["utci_denominator_method"],
            "utci_valid_year_count": df["utci_valid_year_count"],
        }
    )
    for label, field in list(UTCI_HEAT_FIELDS.items()) + list(UTCI_COLD_FIELDS.items()):
        out[field] = df[field].to_numpy()
    return out.reset_index(drop=True)


def build_figure6_a_points(df, classes, continents):
    heat = UTCI_HEAT_FIELDS[">=38C"]
    cold = UTCI_COLD_FIELDS["<=-13C"]
    rows = []
    for continent in continents:
        for _, cls in classes.iterrows():
            sub = df[
                (df["continent5"] == continent)
                & (df["exact_background_class"] == cls["exact_background_class"])
            ]
            if sub.empty:
                # Structurally empty combination: omitted, never zero-filled.
                continue
            codes = sorted(sub["region_code"].dropna().unique().tolist())
            rows.append(
                {
                    "display_region": continent,
                    "exact_background_class": cls["exact_background_class"],
                    "background_class": cls["class_label_en"],
                    "source_region_codes": "; ".join(codes),
                    "source_region_count": len(codes),
                    "feature_count": int(len(sub)),
                    "heat_ge_38c_days_per_year": float(sub[heat].mean()),
                    "cold_le_minus13c_days_per_year": float(sub[cold].mean()),
                }
            )
    return pd.DataFrame(rows)


def build_figure6_a_classmeans(df, classes):
    """Class centre of mass in the (heat >=38C, cold <=-13C) plane.

    No geometry is involved: 'centre' is the mean position in the scatter plane.
    """
    heat = UTCI_HEAT_FIELDS[">=38C"]
    cold = UTCI_COLD_FIELDS["<=-13C"]
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        rows.append(
            {
                "exact_background_class": cls["exact_background_class"],
                "background_class": cls["class_label_en"],
                "feature_count": int(len(sub)),
                "heat_ge_38c_days_per_year": float(sub[heat].mean()),
                "cold_le_minus13c_days_per_year": float(sub[cold].mean()),
            }
        )
    return pd.DataFrame(rows)


def build_figure6_b_thresholds(df, classes):
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        for group, mapping in (("heat", UTCI_HEAT_FIELDS), ("cold", UTCI_COLD_FIELDS)):
            for threshold, field in mapping.items():
                rows.append(
                    {
                        "exact_background_class": cls["exact_background_class"],
                        "background_class": cls["class_label_en"],
                        "metric_group": group,
                        "threshold": threshold,
                        "n_features": int(len(sub)),
                        "mean_annual_days": float(sub[field].mean()),
                    }
                )
    return pd.DataFrame(rows)


def build_figure6_c_oasisiqr(df, classes):
    """Across-oasis quartile spread (NOT inter-model spread)."""
    metrics = [
        ("heat >=38C", UTCI_HEAT_FIELDS[">=38C"], "right"),
        ("cold <=-13C", UTCI_COLD_FIELDS["<=-13C"], "left"),
    ]
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        for metric, field, direction in metrics:
            v = sub[field].to_numpy(dtype=float)
            q25 = float(np.percentile(v, 25))
            med = float(np.median(v))
            q75 = float(np.percentile(v, 75))
            rows.append(
                {
                    "exact_background_class": cls["exact_background_class"],
                    "background_class": cls["class_label_en"],
                    "metric": metric,
                    "plot_direction": direction,
                    "n_features": int(len(sub)),
                    "q25_days_per_year": q25,
                    "median_days_per_year": med,
                    "q75_days_per_year": q75,
                    "plot_q25": q25 if direction == "right" else -q75,
                    "plot_median": med if direction == "right" else -med,
                    "plot_q75": q75 if direction == "right" else -q25,
                }
            )
    return pd.DataFrame(rows)


FUTUREPOP_FIELDS = ["pop_ssp2_2050", "pop_ssp2_2080", "pop_ssp5_2050", "pop_ssp5_2080"]


def build_figure7_polygon(df):
    out = build_figure2_polygon(df)
    out["futurepop_coverage"] = df["futurepop_coverage"].to_numpy()
    out["futurepop_qc"] = df["futurepop_qc"].to_numpy()
    out["futurepop_analysis_method"] = df["futurepop_analysis_method"].to_numpy()
    out["included_in_coverage_aware_totals"] = (
        df["futurepop_coverage"].to_numpy() > 0
    )
    for f in FUTUREPOP_FIELDS:
        out[f] = df[f].to_numpy()
    for f in FUTUREPOP_FIELDS:
        out[f + "_valid_coverage_ratio"] = df[f + "_valid_coverage_ratio"].to_numpy()
    out["worldpop_min_valid_coverage_ratio"] = df[
        "worldpop_min_valid_coverage_ratio"
    ].to_numpy()
    out["no_valid_pixels_any_scenario"] = df[
        "qa_any_worldpop_no_valid_pixels"
    ].to_numpy()
    return out


def build_figure7_classsummary(df, classes):
    total_area = df["polygon_area_km2_geodesic"].sum()
    covered = df[df["futurepop_coverage"] > 0]
    scenario_totals = {f: float(covered[f].sum()) for f in FUTUREPOP_FIELDS}
    rows = []
    for _, cls in classes.iterrows():
        mask = df["exact_background_class"] == cls["exact_background_class"]
        sub = df[mask]
        sub_cov = covered[covered["exact_background_class"] == cls["exact_background_class"]]
        area = float(sub["polygon_area_km2_geodesic"].sum())
        rec = {
            "exact_background_class": cls["exact_background_class"],
            "background_class": cls["class_label_en"],
            "feature_count": int(len(sub)),
            "feature_count_coverage_gt0": int(len(sub_cov)),
            "polygon_area_km2": area,
            "area_share_pct": 100.0 * area / total_area,
        }
        vals = {f: float(sub_cov[f].sum()) / 1e6 for f in FUTUREPOP_FIELDS}
        for scen in ("ssp2", "ssp5"):
            a = vals[f"pop_{scen}_2050"]
            b = vals[f"pop_{scen}_2080"]
            rec[f"pop_{scen}_2050_million"] = a
            rec[f"pop_{scen}_2080_million"] = b
            rec[f"pop_{scen}_2050_2080_change_million"] = b - a
            rec[f"pop_{scen}_2050_2080_change_pct"] = 100.0 * (b - a) / a
        for f in FUTUREPOP_FIELDS:
            rec[f + "_share_pct"] = (
                100.0 * float(sub_cov[f].sum()) / scenario_totals[f]
            )
        nv = sub[sub["qa_any_worldpop_no_valid_pixels"]]
        lc = sub[sub["qa_any_worldpop_low_valid_coverage_095"]]
        rec["no_valid_any_feature_count"] = int(len(nv))
        rec["no_valid_any_area_km2"] = float(nv["polygon_area_km2_geodesic"].sum())
        rec["low_coverage_095_any_feature_count"] = int(len(lc))
        rec["low_coverage_095_any_area_km2"] = float(
            lc["polygon_area_km2_geodesic"].sum()
        )
        rec["mean_min_valid_coverage_ratio"] = float(
            sub["worldpop_min_valid_coverage_ratio"].mean()
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def build_figure7_regionsummary(df, continents):
    covered = df[df["futurepop_coverage"] > 0]
    rows = []
    for continent in continents:
        sub = df[df["continent5"] == continent]
        sub_cov = covered[covered["continent5"] == continent]
        rec = {
            "display_region": continent,
            "feature_count": int(len(sub)),
            "feature_count_coverage_gt0": int(len(sub_cov)),
            "polygon_area_km2": float(sub["polygon_area_km2_geodesic"].sum()),
        }
        for f in FUTUREPOP_FIELDS:
            rec[f + "_million"] = float(sub_cov[f].sum()) / 1e6
        rec["ssp2_delta_million"] = (
            rec["pop_ssp2_2080_million"] - rec["pop_ssp2_2050_million"]
        )
        rec["ssp5_delta_million"] = (
            rec["pop_ssp5_2080_million"] - rec["pop_ssp5_2050_million"]
        )
        rec["no_valid_any_feature_count"] = int(
            sub["qa_any_worldpop_no_valid_pixels"].sum()
        )
        rec["low_coverage_095_any_feature_count"] = int(
            sub["qa_any_worldpop_low_valid_coverage_095"].sum()
        )
        rec["mean_min_valid_coverage_ratio"] = float(
            sub["worldpop_min_valid_coverage_ratio"].mean()
        )
        rec["source_region_codes"] = ";".join(
            sorted(sub["region_code"].dropna().unique().tolist())
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def nex_field(scenario, window, variable):
    return f"nex_{scenario}_{window}_{variable}_delta_1995_2014_median"


def build_figure8_polygon(df):
    out = pd.DataFrame(
        {
            "OasisID": df["OasisID"],
            "continent": df["continent5"],
            "exact_background_class": df["exact_background_class"],
            "background_class": df["class_label_en"],
            "extraction_method": df["nex_method"],
            "nex_qc": df["nex_qc"],
            "nex_model_count_effective_min": df["nex_model_count_effective_min"],
            "nex_model_count_effective_max": df["nex_model_count_effective_max"],
        }
    )
    for scenario in NEX_SCENARIOS:
        for window in NEX_WINDOWS:
            for variable in NEX_VARIABLES:
                f = nex_field(scenario, window, variable)
                out[f] = df[f].to_numpy()
    return out.reset_index(drop=True)


def build_figure8_summary(df, classes, continents):
    fields = {v: nex_field(FIG8_SCENARIO, FIG8_WINDOW, v) for v in NEX_VARIABLES}
    rows = []
    for _, cls in classes.iterrows():
        for continent in continents:
            sub = df[
                (df["exact_background_class"] == cls["exact_background_class"])
                & (df["continent5"] == continent)
            ]
            if sub.empty:
                continue
            rows.append(
                {
                    "class_label": cls["class_label_en"],
                    "exact_background_class": cls["exact_background_class"],
                    "continent5": continent,
                    "scenario": FIG8_SCENARIO,
                    "window": FIG8_WINDOW.replace("_", "-"),
                    "reference_period": "1995-2014",
                    "oasis_count": int(len(sub)),
                    "median_tasmax_delta_degC": float(sub[fields["tasmax"]].median()),
                    "median_tasmin_delta_degC": float(sub[fields["tasmin"]].median()),
                    "median_pr_delta_mm_day": float(sub[fields["pr"]].median()),
                    "fallback_count": int(
                        (sub["nex_method"] == "representative_point_fallback").sum()
                    ),
                }
            )
    return pd.DataFrame(rows)


def strict_mask(df):
    return df["exact_background_class"].isin(["BWh_background", "BWk_background"])


def build_table1_denominators(df):
    strict = strict_mask(df)

    def counts(mask):
        return int(mask.sum()), int((mask & strict).sum())

    def qc_rule(col):
        vc = df[col].value_counts()
        return "; ".join(f"{k}" for k in sorted(vc.index.tolist()))

    specs = []

    m = df["kg_qc"].notna()
    specs.append(
        (
            "Climate class (Koppen-Geiger)",
            f"kg_qc in {{{qc_rule('kg_qc')}}}",
            m,
            "Background classification only; not oasis-interior temperature.",
        )
    )
    m = df["ghsl_qc"].notna()
    specs.append(
        (
            "Social exposure (GHS-POP, GHS-BUILT-S)",
            f"ghsl_qc = {qc_rule('ghsl_qc')}",
            m,
            "Centre-pixel extraction passes for the whole analysis population.",
        )
    )
    m = df["ai_qc"].notna()
    specs.append(
        (
            "Aridity Index",
            f"ai_qc = {qc_rule('ai_qc')}",
            m,
            "True polygon-cell overlap with geometry repair; "
            "ai_true_overlap_status is valid for the whole population, so no "
            "polygon falls outside the aridity validity rule.",
        )
    )
    m = df["et0_qc"].notna()
    specs.append(
        (
            "Evaporative demand (ET0 and ET0 standard deviation)",
            f"et0_qc = {qc_rule('et0_qc')}",
            m,
            "Same true polygon-cell overlap extraction as the Aridity Index; "
            "backs the two ET0 estimands.",
        )
    )
    m = df["terraclimate_qc"].notna()
    specs.append(
        (
            "Water climate (TerraClimate)",
            f"terraclimate_qc = {qc_rule('terraclimate_qc')}",
            m,
            "Complete 1991-2020 record for every polygon.",
        )
    )
    m = df["jrc_qc"].notna()
    specs.append(
        (
            "Surface water (JRC)",
            f"jrc_qc = {qc_rule('jrc_qc')}",
            m,
            "No polygon fails the surface-water join.",
        )
    )
    m = df["utci_qc"].notna()
    n_d15 = int((df["utci_qc"] == "pass_effective_years_D15").sum())
    specs.append(
        (
            "Thermal stress (UTCI, primary D15 rule)",
            f"utci_qc in {{{qc_rule('utci_qc')}}}",
            m,
            f"{n_d15} polygons with fewer than the full 30 valid years are "
            "RETAINED under the effective-valid-year (D15) rule and their day "
            "counts use utci_denominator_method = actual_valid_year_count_D15.",
        )
    )
    m = df["utci_qc"] == "pass_complete_30yr"
    specs.append(
        (
            "Thermal stress (UTCI, complete-30-year sensitivity)",
            "utci_qc = pass_complete_30yr",
            m,
            "Sensitivity denominator only; not the reported primary denominator.",
        )
    )
    m = df["futurepop_coverage"] > 0
    n_novalid = int(df["qa_any_worldpop_no_valid_pixels"].sum())
    specs.append(
        (
            "Future population (primary, coverage > 0)",
            "futurepop_coverage > 0",
            m,
            f"{n_novalid} polygons have no valid FuturePop pixels in at least one "
            "scenario-year; they are not estimable and are excluded from every "
            "coverage-aware total. They are not zero population.",
        )
    )
    m = df["futurepop_coverage"] >= 0.50
    specs.append(
        (
            "Future population (sensitivity, coverage >= 0.50)",
            "futurepop_coverage >= 0.50",
            m,
            "Coverage-restricted sensitivity denominator.",
        )
    )
    m = df["nex_qc"].notna()
    n_poly = int((df["nex_method"] == "polygon_reducer").sum())
    n_fb = int((df["nex_method"] == "representative_point_fallback").sum())
    n_unres = int(df["nex_unresolved_null_row_count"].sum())
    specs.append(
        (
            "Future climate (NEX-GDDP-CMIP6, all polygons)",
            f"nex_qc in {{{qc_rule('nex_qc')}}}",
            m,
            f"{n_poly} polygon reducers and {n_fb} deterministic nearest-valid "
            f"representative-point fallbacks; {n_unres} unresolved rows.",
        )
    )
    m = df["nex_method"] == "polygon_reducer"
    specs.append(
        (
            "Future climate (NEX-GDDP-CMIP6, polygon reducer only)",
            "nex_method = polygon_reducer",
            m,
            "Fallback-free sensitivity denominator.",
        )
    )
    m = df["gdp_qc"].notna()
    n_filled = int(df["gdp2020_total_analysis_was_filled"].sum())
    specs.append(
        (
            "Economy (Kummu gridded GDP v4)",
            f"gdp_qc in {{{qc_rule('gdp_qc')}}}",
            m,
            f"{n_filled} polygons carry an analysis-filled total GDP; the fill "
            "rule is recorded per polygon in gdp2020_total_analysis_fill_flag.",
        )
    )
    m = df["viirs_qc"].notna()
    specs.append(
        (
            "Night lights (VIIRS annual composite)",
            f"viirs_qc = {qc_rule('viirs_qc')}",
            m,
            "Exposure proxy; not a measure of economic output.",
        )
    )

    rows = []
    for module, rule, mask, note in specs:
        valid_n, strict_n = counts(mask)
        rows.append(
            {
                "module": module,
                "valid_rule": rule,
                "valid_n": valid_n,
                "strict_bwh_bwk_n": strict_n,
                "important_exclusion_or_fallback": note,
            }
        )
    return pd.DataFrame(rows)


SUPPORT_RULE_TEXT = (
    "not_supported if the 500 km spatial-block 95% CI contains zero OR the "
    "within-domain Benjamini-Hochberg q >= 0.05; otherwise sensitive if any "
    "scale or alternative-specification check in sensitivity_summary reports "
    "direction_agrees=False or support_agrees=False; otherwise robust."
)


def classify_support(row):
    lo, hi = float(row["ci95_low"]), float(row["ci95_high"])
    q = float(row["fdr_q"])
    summary = str(row["sensitivity_summary"])
    ci_contains_zero = (lo <= 0.0) and (hi >= 0.0)
    if ci_contains_zero:
        return "not_supported", "not_supported: 500 km 95% CI contains zero"
    if q >= 0.05:
        return "not_supported", "not_supported: within-domain FDR q >= 0.05"
    if ("direction_agrees=False" in summary) or ("support_agrees=False" in summary):
        return (
            "sensitive",
            "sensitive: CI excludes zero and q < 0.05, but at least one scale or "
            "alternative-specification check disagrees",
        )
    return (
        "robust",
        "robust: CI excludes zero, q < 0.05, and all scale and "
        "alternative-specification checks agree",
    )


def build_table2_estimands(est):
    out = est.copy()
    decided = out.apply(classify_support, axis=1)
    out["support_class_recomputed"] = [d[0] for d in decided]
    out["support_class_decision_rule"] = [d[1] for d in decided]
    mismatch = out[out["support_class"] != out["support_class_recomputed"]]
    if len(mismatch):
        raise AssertionError(
            "support_class rule does not reproduce the released labels for "
            + ", ".join(mismatch["fact_id"].tolist())
        )
    order = [
        "fact_id",
        "estimand_role",
        "domain",
        "comparison",
        "estimand",
        "statistic",
        "unit",
        "n_bwh",
        "n_bwk",
        "estimate_bwh",
        "estimate_bwk",
        "effect_bwh_minus_bwk",
        "effect_scale",
        "ci95_low",
        "ci95_high",
        "fdr_q",
        "support_class",
        "support_class_recomputed",
        "support_class_decision_rule",
        "sensitivity_summary",
        "display_precision_policy",
        "baseline_id",
    ]
    return out[order]


def build_numericfacts(df, est, classes):
    primary = est.copy()
    primary = primary.rename(columns={"estimand_role": "fact_role"})
    primary["fact_role"] = "primary_inferential"

    cols = [
        "fact_id",
        "fact_role",
        "domain",
        "comparison",
        "estimand",
        "statistic",
        "unit",
        "n_bwh",
        "n_bwk",
        "estimate_bwh",
        "estimate_bwk",
        "effect_bwh_minus_bwk",
        "effect_scale",
        "ci95_low",
        "ci95_high",
        "fdr_q",
        "support_class",
        "sensitivity_summary",
        "display_precision_policy",
        "baseline_id",
    ]
    primary = primary[cols]

    bwh = df[df["exact_background_class"] == "BWh_background"]
    bwk = df[df["exact_background_class"] == "BWk_background"]
    baseline = df["baseline_id"].unique()[0]

    def blank_row(fact_id, role, domain, comparison, estimand, statistic, unit,
                  n_bwh, n_bwk, e_bwh, e_bwk, summary, precision):
        return {
            "fact_id": fact_id,
            "fact_role": role,
            "domain": domain,
            "comparison": comparison,
            "estimand": estimand,
            "statistic": statistic,
            "unit": unit,
            "n_bwh": n_bwh,
            "n_bwk": n_bwk,
            "estimate_bwh": e_bwh,
            "estimate_bwk": e_bwk,
            "effect_bwh_minus_bwk": np.nan,
            "effect_scale": "not_inferential",
            "ci95_low": np.nan,
            "ci95_high": np.nan,
            "fdr_q": np.nan,
            "support_class": "descriptive_only",
            "sensitivity_summary": summary,
            "display_precision_policy": precision,
            "baseline_id": baseline,
        }

    extra = []
    class_counts = "; ".join(
        f"{r['class_label_en']} n={int((df['exact_background_class'] == r['exact_background_class']).sum())}"
        for _, r in classes.iterrows()
    )
    extra.append(
        blank_row(
            "F04-CONTEXT-01",
            "descriptive_context",
            "structure",
            "global oasis inventory",
            "oasis_count",
            "descriptive count",
            "oases",
            len(bwh),
            len(bwk),
            float(len(bwh)),
            float(len(bwk)),
            f"Analysis population n={len(df)}. Class composition: {class_counts}.",
            "integer counts",
        )
    )
    extra.append(
        blank_row(
            "F04-CONTEXT-02",
            "descriptive_context",
            "structure",
            "global oasis area",
            "polygon_area_km2_geodesic_total",
            "descriptive sum",
            "km2",
            len(bwh),
            len(bwk),
            float(bwh["polygon_area_km2_geodesic"].sum()),
            float(bwk["polygon_area_km2_geodesic"].sum()),
            f"Global total across all classes = "
            f"{df['polygon_area_km2_geodesic'].sum():.6f} km2.",
            "two decimals for display",
        )
    )
    extra.append(
        blank_row(
            "F04-CONTEXT-03",
            "descriptive_context",
            "structure",
            "patch-area upper tail",
            "polygon_area_km2_geodesic_p99",
            "descriptive 99th percentile",
            "km2",
            len(bwh),
            len(bwk),
            float(np.percentile(bwh["polygon_area_km2_geodesic"].to_numpy(), 99)),
            float(np.percentile(bwk["polygon_area_km2_geodesic"].to_numpy(), 99)),
            "Linear-interpolation percentile across oases within each class.",
            "two decimals for display",
        )
    )

    covered = df[df["futurepop_coverage"] > 0]
    cbwh = covered[covered["exact_background_class"] == "BWh_background"]
    cbwk = covered[covered["exact_background_class"] == "BWk_background"]
    n_cov = int((df["futurepop_coverage"] > 0).sum())
    n_cov50 = int((df["futurepop_coverage"] >= 0.50).sum())
    n_nov = int(df["qa_any_worldpop_no_valid_pixels"].sum())
    cov_note = (
        f"Coverage-aware descriptive total over futurepop_coverage > 0. "
        f"Release denominators: coverage > 0 n={n_cov}; coverage >= 0.50 "
        f"n={n_cov50}; no valid pixels n={n_nov} (not estimable, not zero)."
    )
    for i, field in enumerate(FUTUREPOP_FIELDS, start=1):
        extra.append(
            blank_row(
                f"F04-FUTUREPOP-{i:02d}",
                "descriptive_context",
                "futurepop",
                "coverage-aware class total",
                field,
                "coverage-aware descriptive total",
                "persons",
                len(cbwh),
                len(cbwk),
                float(cbwh[field].sum()),
                float(cbwk[field].sum()),
                cov_note,
                "persons, no rounding in source data",
            )
        )
    extra.append(
        blank_row(
            "F04-FUTUREPOP-05",
            "descriptive_context",
            "futurepop",
            "coverage accounting",
            "futurepop_coverage_denominator",
            "descriptive denominator",
            "oases",
            len(cbwh),
            len(cbwk),
            float(len(cbwh)),
            float(len(cbwk)),
            cov_note,
            "integer counts",
        )
    )

    return pd.concat([primary, pd.DataFrame(extra)], ignore_index=True)[cols]


def build_supp_s1_gdp(df, classes):
    global_total = float(df["gdp2020_total_analysis_2017_int_usd"].sum())
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        total = float(sub["gdp2020_total_analysis_2017_int_usd"].sum())
        filled = int(sub["gdp2020_total_analysis_was_filled"].sum())
        rows.append(
            {
                "exact_background_class": cls["exact_background_class"],
                "background_class": cls["class_label_en"],
                "patches": int(len(sub)),
                "originally_missing_then_analysis_filled_total_gdp": f"{filled}/{filled}",
                "analysis_total_gdp_2020_1e12_2017_int_usd": total / 1e12,
                "analysis_gdp_share_pct": 100.0 * total / global_total,
                "area_weighted_gdp_per_capita_2017_int_usd": weighted_mean(
                    sub["gdp2020_pc_ppp2021_int_usd_area_mean"],
                    sub["polygon_area_km2_geodesic"],
                ),
                "gdp_per_ghsl_population_2017_int_usd_per_person": total
                / float(sub["pop_sum_2020"].sum()),
            }
        )
    return pd.DataFrame(rows)


def build_supp_s5_nex(df):
    n_poly = int((df["nex_method"] == "polygon_reducer").sum())
    n_fb = int((df["nex_method"] == "representative_point_fallback").sum())
    n_unres = int(df["nex_unresolved_null_row_count"].sum())
    mn = sorted(df["nex_model_count_effective_min"].unique().tolist())
    mx = sorted(df["nex_model_count_effective_max"].unique().tolist())
    sw = sorted(df["nex_scenario_window_count"].unique().tolist())
    if mn != mx:
        raise AssertionError("effective NEX model count is not constant")
    rows = [
        {
            "component": "Polygon reducer",
            "count_or_rule": f"{n_poly} oases",
            "interpretation": (
                "Area reduction over the full oasis polygon; the preferred "
                "extraction path."
            ),
        },
        {
            "component": "Nearest-valid representative-point fallback",
            "count_or_rule": f"{n_fb} oases",
            "interpretation": (
                "Deterministic fallback used where the polygon does not intersect "
                "a valid source cell; recorded per oasis in nex_method."
            ),
        },
        {
            "component": "Unresolved rows",
            "count_or_rule": f"{n_unres} rows",
            "interpretation": (
                "Every scenario-window-variable combination resolves to a value; "
                "there is no silent gap."
            ),
        },
        {
            "component": "Ensemble members",
            "count_or_rule": (
                f"{mn[0]} models across {sw[0]} scenario-window combinations"
            ),
            "interpretation": (
                "Effective model count is identical for every oasis and every "
                "combination (nex_model_count_effective_min equals _max)."
            ),
        },
        {
            "component": "Statistic and dispersion reporting",
            "count_or_rule": "ensemble median; spatial-block bootstrap intervals",
            "interpretation": (
                "Only the across-model ensemble median is released. Per-model "
                "values are not redistributed, so an inter-model interquartile "
                "range cannot be computed from this release; the intervals in "
                "Table2_Estimands are spatial-block bootstrap intervals and the "
                "two kinds of uncertainty must not be combined."
            ),
        },
    ]
    return pd.DataFrame(rows)


def build_supp_s6_utci_d15(df):
    sub = df[df["utci_denominator_method"] == "actual_valid_year_count_D15"]
    out = pd.DataFrame(
        {
            "OasisID": sub["OasisID"],
            "region_code": sub["region_code"],
            "continent": sub["continent5"],
            "feature_index": sub["feature_index"],
            "exact_background_class": sub["exact_background_class"],
            "background_class": sub["class_label_en"],
            "utci_qc": sub["utci_qc"],
            "utci_denominator_method": sub["utci_denominator_method"],
            "valid_year_count": sub["utci_valid_year_count"],
        }
    )
    for field in list(UTCI_HEAT_FIELDS.values()) + list(UTCI_COLD_FIELDS.values()):
        out[field] = sub[field].to_numpy()
    return out.reset_index(drop=True)


def build_suppfig_s1_polygon(df):
    out = pd.DataFrame(
        {
            "OasisID": df["OasisID"],
            "continent": df["continent5"],
            "exact_background_class": df["exact_background_class"],
            "background_class": df["class_label_en"],
            "gdp2020_total_analysis_2017_int_usd": df[
                "gdp2020_total_analysis_2017_int_usd"
            ],
            "gdp2020_per_capita_2017_int_usd_area_mean": df[
                "gdp2020_pc_ppp2021_int_usd_area_mean"
            ],
            "gdp2020_total_analysis_per_ghsl_pop2020_2017_int_usd_per_person": df[
                "gdp2020_total_analysis_per_ghsl_pop2020"
            ],
            "gdp2020_total_analysis_was_filled": df["gdp2020_total_analysis_was_filled"],
            "gdp2020_total_analysis_fill_flag": df["gdp2020_total_analysis_fill_flag"],
            "viirs2020_avg_masked_rad_mean": df["viirs2020_avg_masked_rad_mean"],
            "viirs2020_avg_masked_rad_median": df["viirs2020_avg_masked_rad_median"],
            "viirs2020_avg_masked_rad_p90": df["viirs2020_avg_masked_rad_p90"],
            "viirs2020_lit_area_fraction": df["viirs2020_lit_area_fraction"],
            "viirs2020_sum_proxy_rad_km2": df["viirs2020_sum_proxy_rad_km2"],
            "viirs_qc_tier": df["viirs_qc_tier"],
        }
    )
    return out.reset_index(drop=True)


def build_suppfig_s1_classsummary(df, classes):
    global_total = float(df["gdp2020_total_analysis_2017_int_usd"].sum())
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        total = float(sub["gdp2020_total_analysis_2017_int_usd"].sum())
        rows.append(
            {
                "exact_background_class": cls["exact_background_class"],
                "background_class": cls["class_label_en"],
                "feature_count": int(len(sub)),
                "gdp_total_2017_int_usd": total,
                "gdp_total_share_pct": 100.0 * total / global_total,
                "gdp_filled_count": int(sub["gdp2020_total_analysis_was_filled"].sum()),
                "estimand_median_definition": ESTIMAND_MEDIAN_DEFINITION,
                "estimand_median_gdp_total_2017_int_usd": estimand_median(
                    sub["gdp2020_total_analysis_2017_int_usd"]
                ),
                "estimand_median_gdp_per_capita_2017_int_usd": estimand_median(
                    sub["gdp2020_pc_ppp2021_int_usd_area_mean"]
                ),
                "viirs_mean_radiance_class_mean": float(
                    sub["viirs2020_avg_masked_rad_mean"].mean()
                ),
                "estimand_median_viirs_mean_radiance": estimand_median(
                    sub["viirs2020_avg_masked_rad_mean"]
                ),
                "viirs_lit_area_fraction_class_mean": float(
                    sub["viirs2020_lit_area_fraction"].mean()
                ),
                "estimand_median_viirs_lit_area_fraction": estimand_median(
                    sub["viirs2020_lit_area_fraction"]
                ),
                "viirs_sum_proxy_rad_km2_total": float(
                    sub["viirs2020_sum_proxy_rad_km2"].sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def build_scale_sensitivity(df, est, t9):
    """31 estimands x three spatial-block scales.

    The 250 km and 1,000 km intervals are the LOCKED analysis intervals taken
    from the sensitivity evidence pack (columns ci_lo_locked / ci_hi_locked);
    the 500 km interval is the primary interval from primary_estimands_31.csv.
    """
    strict = df[strict_mask(df)]
    blocks = {
        250: int(strict["block_250km"].nunique()),
        500: int(strict["block_500km"].nunique()),
        1000: int(strict["block_1000km"].nunique()),
    }
    rows = []
    for _, e in est.iterrows():
        rec = {
            "fact_id": e["fact_id"],
            "domain": e["domain"],
            "estimand": e["estimand"],
            "unit": e["unit"],
            "effect_scale": e["effect_scale"],
            "effect_bwh_minus_bwk": e["effect_bwh_minus_bwk"],
            "primary_support_class": e["support_class"],
        }
        for scale in (250, 500, 1000):
            rec[f"occupied_blocks_{scale}km"] = blocks[scale]
        rec["ci95_low_500km"] = e["ci95_low"]
        rec["ci95_high_500km"] = e["ci95_high"]
        rec["fdr_q_500km"] = e["fdr_q"]
        rec["ci_source_500km"] = "data/primary_estimands_31.csv"
        for scale in (250, 1000):
            m = t9[(t9["fact_id"] == e["fact_id"]) & (t9["scale_km"] == scale)]
            if len(m) != 1:
                raise AssertionError(
                    f"expected exactly one locked record for {e['fact_id']} at {scale} km"
                )
            m = m.iloc[0]
            if int(m["occupied_blocks"]) != blocks[scale]:
                raise AssertionError(
                    f"occupied block count mismatch for {e['fact_id']} at {scale} km"
                )
            rec[f"ci95_low_{scale}km"] = float(m["ci_lo_locked"])
            rec[f"ci95_high_{scale}km"] = float(m["ci_hi_locked"])
            rec[f"valid_replicates_{scale}km"] = int(m["valid_replicates"])
            rec[f"invalid_attempts_{scale}km"] = int(m["invalid_attempts"])
            rec[f"direction_agrees_{scale}km"] = bool(m["direction_agrees_primary"])
            rec[f"support_agrees_{scale}km"] = bool(m["support_agrees_primary"])
            rec[f"ci_source_{scale}km"] = "locked analysis run (seed-matched)"
        rows.append(rec)
    out = pd.DataFrame(rows)
    order = [
        "fact_id",
        "domain",
        "estimand",
        "unit",
        "effect_scale",
        "effect_bwh_minus_bwk",
        "primary_support_class",
        "occupied_blocks_250km",
        "ci95_low_250km",
        "ci95_high_250km",
        "valid_replicates_250km",
        "invalid_attempts_250km",
        "direction_agrees_250km",
        "support_agrees_250km",
        "ci_source_250km",
        "occupied_blocks_500km",
        "ci95_low_500km",
        "ci95_high_500km",
        "fdr_q_500km",
        "ci_source_500km",
        "occupied_blocks_1000km",
        "ci95_low_1000km",
        "ci95_high_1000km",
        "valid_replicates_1000km",
        "invalid_attempts_1000km",
        "direction_agrees_1000km",
        "support_agrees_1000km",
        "ci_source_1000km",
    ]
    return out[order]


def build_effective_n(df, cfg_est):
    strict = df[strict_mask(df)]
    blocks = {
        250: int(strict["block_250km"].nunique()),
        500: int(strict["block_500km"].nunique()),
        1000: int(strict["block_1000km"].nunique()),
    }
    bwh = df[df["exact_background_class"] == "BWh_background"]
    bwk = df[df["exact_background_class"] == "BWk_background"]
    rows = []
    for _, e in cfg_est.iterrows():
        field = e["source_field"]
        gate = qa_gate_for(field)
        if gate == "none":
            gate_bwh, gate_bwk = bwh, bwk
        else:
            gate_bwh = bwh[bwh[gate].notna()]
            gate_bwk = bwk[bwk[gate].notna()]
        eff_bwh = int(gate_bwh[field].notna().sum())
        eff_bwk = int(gate_bwk[field].notna().sum())
        rows.append(
            {
                "fact_id": e["fact_id"],
                "domain": e["domain"],
                "estimand": e["estimand"],
                "source_field": field,
                "implementation_method": e["implementation_method"],
                "weight_field": e["weight_field"] if pd.notna(e["weight_field"]) else "",
                "qa_gate_column": gate,
                "class_total_bwh": int(len(bwh)),
                "class_total_bwk": int(len(bwk)),
                "effective_n_bwh": eff_bwh,
                "effective_n_bwk": eff_bwk,
                "effective_n_total": eff_bwh + eff_bwk,
                "dropped_bwh": int(len(bwh)) - eff_bwh,
                "dropped_bwk": int(len(bwk)) - eff_bwk,
                "raw_nan_bwh": int(bwh[field].isna().sum()),
                "raw_nan_bwk": int(bwk[field].isna().sum()),
                "zero_valued_bwh": int((bwh[field] == 0).sum()),
                "zero_valued_bwk": int((bwk[field] == 0).sum()),
                "occupied_blocks_250km": blocks[250],
                "occupied_blocks_500km": blocks[500],
                "occupied_blocks_1000km": blocks[1000],
                "occupied_blocks_500km_bwh": int(bwh["block_500km"].nunique()),
                "occupied_blocks_500km_bwk": int(bwk["block_500km"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def build_spatial_blocks(df, classes):
    strict = df[strict_mask(df)]
    bwh = df[df["exact_background_class"] == "BWh_background"]
    bwk = df[df["exact_background_class"] == "BWk_background"]
    rows = []
    for scale, col in ((250, "block_250km"), (500, "block_500km"), (1000, "block_1000km")):
        sb, sk = set(bwh[col]), set(bwk[col])
        rec = {
            "scale_km": scale,
            "blocks_all_population": int(df[col].nunique()),
            "blocks_strict_bwh_bwk": int(strict[col].nunique()),
            "blocks_bwh": len(sb),
            "blocks_bwk": len(sk),
            "blocks_union_bwh_bwk": len(sb | sk),
            "blocks_shared_bwh_bwk": len(sb & sk),
            "blocks_bwh_only": len(sb - sk),
            "blocks_bwk_only": len(sk - sb),
        }
        for _, cls in classes.iterrows():
            key = cls["exact_background_class"]
            rec[f"blocks_{key}"] = int(
                df.loc[df["exact_background_class"] == key, col].nunique()
            )
        rows.append(rec)
    return pd.DataFrame(rows)


def build_futurepop_coverage(df, classes):
    ratio_fields = [f + "_valid_coverage_ratio" for f in FUTUREPOP_FIELDS] + [
        "worldpop_min_valid_coverage_ratio",
        "futurepop_coverage",
    ]
    qc_values = sorted(df["futurepop_qc"].dropna().unique().tolist())
    method_values = sorted(df["futurepop_analysis_method"].dropna().unique().tolist())
    rows = []
    for _, cls in classes.iterrows():
        sub = df[df["exact_background_class"] == cls["exact_background_class"]]
        rec = {
            "exact_background_class": cls["exact_background_class"],
            "background_class": cls["class_label_en"],
            "feature_count": int(len(sub)),
        }
        for f in ratio_fields:
            v = sub[f]
            rec[f + "__mean"] = float(v.mean())
            rec[f + "__median"] = float(v.median())
            rec[f + "__n_eq0"] = int((v == 0).sum())
            rec[f + "__n_lt025"] = int((v < 0.25).sum())
            rec[f + "__n_lt050"] = int((v < 0.50).sum())
            rec[f + "__n_lt095"] = int((v < 0.95).sum())
            rec[f + "__n_ge099"] = int((v >= 0.99).sum())
        for q in qc_values:
            rec["futurepop_qc::" + q] = int((sub["futurepop_qc"] == q).sum())
        for m in method_values:
            rec["futurepop_analysis_method::" + m] = int(
                (sub["futurepop_analysis_method"] == m).sum()
            )
        rows.append(rec)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Data dictionary
# --------------------------------------------------------------------------

UNIT_MAP = {
    "OasisID": "identifier",
    "oasisid": "identifier",
    "continent": "category",
    "continent5": "category",
    "display_region": "category",
    "region_code": "category",
    "source_region_codes": "category list",
    "source_region_count": "count",
    "exact_background_class": "category",
    "background_class": "category",
    "class_label": "category",
    "feature_index": "identifier",
    "feature_count": "oases",
    "feature_count_coverage_gt0": "oases",
    "n_features": "oases",
    "oasis_count": "oases",
    "patches": "oases",
    "polygon_area_km2": "km2",
    "polygon_area_km2_geodesic": "km2",
    "area_km2": "km2",
    "area_million_km2": "million km2",
    "area_share_pct": "%",
    "area_share_of_global_pct": "%",
    "mean_area_km2": "km2",
    "median_area_km2": "km2",
    "max_area_km2": "km2",
    "area_lt_100_km2": "km2",
    "area_lt_100_share_of_class_pct": "%",
    "count_lt_10_km2": "oases",
    "count_lt_100_km2": "oases",
    "area_bin": "km2 interval",
    "ghsl_population_2020_persons": "persons",
    "population_2020": "persons",
    "population_2020_million": "million persons",
    "ghsl_population_density_persons_per_km2": "persons km-2",
    "population_density_per_km2": "persons km-2",
    "ghsl_built_up_area_2020_km2": "km2",
    "built_up_2020_km2": "km2",
    "ghsl_built_up_area_fraction": "share",
    "built_up_fraction_pct": "%",
    "aridity_index": "index",
    "aridity_index_scaled": "index",
    "et0_mm_yr": "mm yr-1",
    "et0_sd_mm_yr": "mm yr-1",
    "occurrence_area_weighted_pct": "%",
    "recurrence_area_weighted_pct": "%",
    "utci_valid_year_count": "years",
    "valid_year_count": "years",
    "mean_annual_days": "days yr-1",
    "heat_ge_38c_days_per_year": "days yr-1",
    "cold_le_minus13c_days_per_year": "days yr-1",
    "q25_days_per_year": "days yr-1",
    "median_days_per_year": "days yr-1",
    "q75_days_per_year": "days yr-1",
    "plot_q25": "days yr-1 (signed for plotting)",
    "plot_median": "days yr-1 (signed for plotting)",
    "plot_q75": "days yr-1 (signed for plotting)",
    "futurepop_coverage": "ratio",
    "worldpop_min_valid_coverage_ratio": "ratio",
    "mean_min_valid_coverage_ratio": "ratio",
    "median_tasmax_delta_degC": "degC",
    "median_tasmin_delta_degC": "degC",
    "median_pr_delta_mm_day": "mm day-1",
    "valid_n": "oases",
    "strict_bwh_bwk_n": "oases",
    "n_bwh": "oases",
    "n_bwk": "oases",
    "fdr_q": "probability",
    "fdr_q_500km": "probability",
    "scale_km": "km",
    "gdp_total_2017_int_usd": "PPP USD (2017 international dollars)",
    "estimand_median_gdp_total_2017_int_usd": "PPP USD (2017 international dollars)",
    "estimand_median_gdp_per_capita_2017_int_usd": (
        "PPP USD (2017 international dollars per person)"
    ),
    "estimand_median_definition": "text",
    "gdp_total_share_pct": "%",
    "gdp_filled_count": "oases",
    "analysis_total_gdp_2020_1e12_2017_int_usd": (
        "trillion PPP USD (2017 international dollars)"
    ),
    "analysis_gdp_share_pct": "%",
    "area_weighted_gdp_per_capita_2017_int_usd": (
        "PPP USD (2017 international dollars per person)"
    ),
    "gdp_per_ghsl_population_2017_int_usd_per_person": (
        "PPP USD (2017 international dollars per person)"
    ),
    "gdp2020_total_analysis_2017_int_usd": "PPP USD (2017 international dollars)",
    "gdp2020_per_capita_2017_int_usd_area_mean": (
        "PPP USD (2017 international dollars per person)"
    ),
    "gdp2020_total_analysis_per_ghsl_pop2020_2017_int_usd_per_person": (
        "PPP USD (2017 international dollars per person)"
    ),
    "viirs2020_avg_masked_rad_mean": "nW cm-2 sr-1",
    "viirs2020_avg_masked_rad_median": "nW cm-2 sr-1",
    "viirs2020_avg_masked_rad_p90": "nW cm-2 sr-1",
    "viirs_mean_radiance_class_mean": "nW cm-2 sr-1",
    "estimand_median_viirs_mean_radiance": "nW cm-2 sr-1",
    "viirs2020_lit_area_fraction": "share",
    "viirs_lit_area_fraction_class_mean": "share",
    "estimand_median_viirs_lit_area_fraction": "share",
    "viirs2020_sum_proxy_rad_km2": "nW cm-2 sr-1 km2",
    "viirs_sum_proxy_rad_km2_total": "nW cm-2 sr-1 km2",
}

DEFINITION_MAP = {
    "OasisID": "Stable oasis identifier of the current analysis population.",
    "oasisid": "Stable oasis identifier of the current analysis population.",
    "continent": "Five-way continental grouping used for display.",
    "display_region": "Five-way continental grouping used for display.",
    "continent5": "Five-way continental grouping used for display.",
    "region_code": "Analysis sub-region code assigned to the oasis.",
    "source_region_codes": (
        "Sorted, semicolon-separated list of the analysis sub-region codes "
        "contributing to this display group."
    ),
    "source_region_count": "Number of distinct sub-region codes in the group.",
    "exact_background_class": (
        "Machine background-climate class key from the Koppen-Geiger overlay."
    ),
    "background_class": "Human-readable label of the background-climate class.",
    "class_label": "Human-readable label of the background-climate class.",
    "feature_index": "Positional index of the oasis within its source region.",
    "polygon_area_km2": "Geodesic polygon area of the fixed 2020 oasis boundary.",
    "polygon_area_km2_geodesic": "Geodesic polygon area of the fixed 2020 oasis boundary.",
    "area_bin": (
        "Area class interval, left-closed and right-open, assigned from the "
        "geodesic polygon area."
    ),
    "aridity_index": (
        "Aridity Index for the oasis, extracted by true polygon-cell overlap and "
        "rescaled from the raw product by the release scale factor."
    ),
    "aridity_index_scaled": (
        "Area-weighted class mean of the rescaled Aridity Index."
    ),
    "et0_mm_yr": (
        "Reference evapotranspiration extracted by true polygon-cell overlap; "
        "annual total."
    ),
    "et0_sd_mm_yr": (
        "Area-weighted mean of the cell-level standard deviation of annual ET0; "
        "descriptive spread of the source grid, not a propagated uncertainty."
    ),
    "utci_valid_year_count": "Number of UTCI years with a valid record.",
    "valid_year_count": "Number of UTCI years with a valid record.",
    "utci_qc": (
        "UTCI module validity status; pass_effective_years_D15 marks oases "
        "retained on fewer than the full 30 years."
    ),
    "utci_denominator_method": (
        "Denominator actually used to convert UTCI exceedance days into a mean "
        "annual rate."
    ),
    "futurepop_coverage": (
        "Minimum valid FuturePop coverage ratio across the scenario-year "
        "combinations."
    ),
    "futurepop_qc": "FuturePop coverage QC status for the oasis.",
    "futurepop_analysis_method": (
        "Extraction path actually used for the FuturePop values of this oasis."
    ),
    "included_in_coverage_aware_totals": (
        "True when futurepop_coverage is above zero, i.e. when the oasis "
        "contributes to every coverage-aware total in this workbook. False rows "
        "carry deterministic nearest-valid-grid substitutions and must not be "
        "read as polygon-aggregated exposure."
    ),
    "no_valid_pixels_any_scenario": (
        "True when at least one scenario-year has no valid FuturePop pixel inside "
        "the polygon."
    ),
    "extraction_method": "NEX extraction path used for this oasis.",
    "nex_qc": "NEX module validity status.",
    "nex_model_count_effective_min": (
        "Smallest effective ensemble model count across the scenario-window "
        "combinations of this oasis."
    ),
    "nex_model_count_effective_max": (
        "Largest effective ensemble model count across the scenario-window "
        "combinations of this oasis."
    ),
    "scenario": "Emissions scenario summarised on this row.",
    "window": "Future time window summarised on this row.",
    "reference_period": "Historical reference period for the reported change.",
    "fallback_count": (
        "Number of oases in the group whose NEX values came from the "
        "representative-point fallback."
    ),
    "weighting_scheme": (
        "Explicit statement of which columns on this row are area-weighted and "
        "which are unweighted class means."
    ),
    "metric_group": "Whether the row reports heat stress or cold stress.",
    "threshold": "UTCI threshold defining the exceedance day count.",
    "metric": "UTCI metric summarised on this row.",
    "plot_direction": "Side of the diverging bar on which the metric is drawn.",
    "gdp2020_total_analysis_was_filled": (
        "True when the analysis total GDP for this oasis was filled rather than "
        "observed."
    ),
    "gdp2020_total_analysis_fill_flag": "Which fill rule produced the analysis total GDP.",
    "estimand_median_definition": (
        "Median definition used by the estimand_median_* columns on this row. "
        "It is the definition of the patch-median estimator behind "
        "Table2_Estimands, not the ordinary linear-interpolation median used by "
        "the descriptive figure sheets."
    ),
    "estimand_median_gdp_total_2017_int_usd": (
        "Class median total GDP under the estimand median definition; the log "
        "ratio of the BWh and BWk values reproduces F04-PRIMARY-26."
    ),
    "estimand_median_gdp_per_capita_2017_int_usd": (
        "Class median GDP per capita under the estimand median definition; "
        "reproduces F04-PRIMARY-27."
    ),
    "estimand_median_viirs_mean_radiance": (
        "Class median VIIRS mean radiance under the estimand median definition; "
        "reproduces F04-PRIMARY-28."
    ),
    "estimand_median_viirs_lit_area_fraction": (
        "Class median VIIRS lit-area fraction under the estimand median "
        "definition; reproduces F04-PRIMARY-29."
    ),
    "viirs_qc_tier": "VIIRS coverage QC tier for the oasis.",
    "support_class": (
        "Released evidential support label for the estimand."
    ),
    "support_class_recomputed": (
        "Support label recomputed inside this build from the released interval, "
        "q value and sensitivity summary; it must equal support_class."
    ),
    "support_class_decision_rule": (
        "Which branch of the support rule produced the label for this estimand."
    ),
    "primary_support_class": "Released support label at the primary block scale.",
    "ci_source_250km": "Provenance of the 250 km interval on this row.",
    "ci_source_500km": "Provenance of the 500 km interval on this row.",
    "ci_source_1000km": "Provenance of the 1,000 km interval on this row.",
    "qa_gate_column": (
        "Module QC column used to define the valid sample for this estimand."
    ),
    "module": "Analysis module whose denominator the row reports.",
    "valid_rule": "Rule that defines the valid sample for the module.",
    "valid_n": "Oases satisfying the rule across the whole analysis population.",
    "strict_bwh_bwk_n": (
        "Oases satisfying the rule inside the strict BWh-versus-BWk contrast."
    ),
    "important_exclusion_or_fallback": (
        "Exclusions, fallbacks and not-estimable cases the reader must know about."
    ),
    "component": "Extraction or inference component described by the row.",
    "count_or_rule": "Count or rule value for the component.",
    "interpretation": "How the component should be read.",
    "sheet": "Workbook sheet the field belongs to.",
    "field": "Column header as written in that sheet.",
    "unit": "Unit of the field.",
    "definition": "What the field means.",
    "missing_value_meaning": "How a blank cell in the field must be read.",
    "release_field": (
        "Name of the underlying field in the public release, when the sheet "
        "column was renamed."
    ),
}

MODULE_NE_HINTS = [
    ("futurepop", "pop_ssp"),
    ("futurepop", "futurepop"),
    ("utci", "utci"),
    ("nex", "nex_"),
    ("gdp", "gdp"),
    ("viirs", "viirs"),
    ("jrc", "jrc"),
    ("terraclimate", "terraclimate"),
]

IDENTITY_FIELDS = {
    "OasisID",
    "oasisid",
    "continent",
    "continent5",
    "display_region",
    "exact_background_class",
    "background_class",
    "class_label",
    "feature_index",
    "region_code",
    "polygon_area_km2",
    "polygon_area_km2_geodesic",
    "sheet",
    "field",
    "unit",
    "definition",
    "missing_value_meaning",
    "Item",
    "Description",
}


def build_data_dictionary(sheets, cfg_est, released_dd, renames):
    """One row per (sheet, field) across every data sheet in the workbook."""
    est_units = dict(zip(cfg_est["estimand"], cfg_est["unit"]))
    dd_desc = {}
    for _, r in released_dd.iterrows():
        if isinstance(r["description"], str) and r["description"].strip():
            dd_desc[r["field"]] = r["description"].strip()
    # The released dictionary entry for futurepop_analysis_method quotes counts
    # from the superseded 3,443-oasis baseline, so it is not propagated here.
    dd_desc.pop("futurepop_analysis_method", None)
    dd_group = dict(zip(released_dd["field"], released_dd["field_group"]))

    rows = []
    for sheet_name, frame in sheets.items():
        if sheet_name in ("README", "Data_Dictionary"):
            continue
        for field in frame.columns:
            release_field = renames.get((sheet_name, field), "")
            lookup = release_field or field
            unit = UNIT_MAP.get(field)
            if unit is None:
                unit = UNIT_MAP.get(lookup)
            if unit is None and field in est_units:
                unit = est_units[field]
            if unit is None:
                unit = infer_unit(field)
            definition = DEFINITION_MAP.get(field)
            if definition is None:
                definition = dd_desc.get(lookup)
            if definition is None:
                definition = infer_definition(field, lookup, dd_group.get(lookup, ""))
            if field in IDENTITY_FIELDS or field in (
                "exact_background_class",
                "background_class",
            ):
                missing = NE_IDENTITY
            else:
                missing = NE_POLICY
            rows.append(
                {
                    "sheet": sheet_name,
                    "field": field,
                    "release_field": release_field,
                    "unit": unit,
                    "definition": definition,
                    "missing_value_meaning": missing,
                }
            )
    return pd.DataFrame(rows)


def infer_unit(field):
    f = field.lower()
    if f.endswith("_pct") or f.endswith("_share_pct") or "_pct_" in f:
        return "%"
    if f.endswith("_km2"):
        return "km2"
    if f.endswith("_million"):
        return "million persons"
    if "coverage_ratio" in f or f.endswith("_ratio"):
        return "ratio"
    if f.startswith("pop_ssp") and not f.endswith("_million"):
        return "persons"
    if "days" in f:
        return "days yr-1"
    if f.endswith("_mm") or "mean_annual_mm" in f:
        return "mm yr-1"
    if "mean_monthly_mm" in f:
        return "mm month-1"
    if "tasmax" in f or "tasmin" in f:
        return "degC"
    if f.endswith("_pr_delta_1995_2014_median") or "pr_delta" in f:
        return "mm day-1"
    if f.startswith("ci95_") or f.startswith("effect"):
        return "estimand unit; see the unit column of Table2_Estimands"
    if f.startswith("blocks") or "occupied_blocks" in f:
        return "spatial blocks"
    if f.startswith("n_") or f.endswith("_count") or f.startswith("count_"):
        return "count"
    if f.startswith("qa_") or f.endswith("_qc") or f.startswith("direction_") or f.startswith("support_agrees"):
        return "boolean or status"
    if "fraction" in f or f.endswith("_share"):
        return "share"
    return "category or text"


def infer_definition(field, lookup, group):
    if group:
        return (
            f"Field {lookup} of the released analysis input "
            f"({group}); see data/data_dictionary.csv."
        )
    return (
        f"Derived in this workbook from the released analysis input; see "
        f"scripts/build_source_data_workbook.py for the exact expression."
    )


# --------------------------------------------------------------------------
# README sheet
# --------------------------------------------------------------------------


def build_readme(df, est, cfg, excluded, classes, dropped_notes, omitted_notes,
                 sheet_names):
    n = len(df)
    bwh = int((df["exact_background_class"] == "BWh_background").sum())
    bwk = int((df["exact_background_class"] == "BWk_background").sum())
    mixed = int((df["exact_background_class"] == "mixed_BWh_BWk").sum())
    nonbw = int((df["exact_background_class"] == "non_BWh_BWk_background").sum())
    strict = bwh + bwk
    total_area = float(df["polygon_area_km2_geodesic"].sum())
    baseline = df["baseline_id"].unique()[0]
    domains = est["domain"].value_counts()
    domain_txt = "; ".join(f"{k} {int(v)}" for k, v in domains.sort_index().items())
    support = est["support_class"].value_counts()
    support_txt = "; ".join(f"{k} {int(v)}" for k, v in support.sort_index().items())
    strict_df = df[strict_mask(df)]
    b500 = int(strict_df["block_500km"].nunique())
    b250 = int(strict_df["block_250km"].nunique())
    b1000 = int(strict_df["block_1000km"].nunique())
    n_d15 = int((df["utci_qc"] == "pass_effective_years_D15").sum())
    n_full = int((df["utci_qc"] == "pass_complete_30yr").sum())
    n_cov = int((df["futurepop_coverage"] > 0).sum())
    n_cov50 = int((df["futurepop_coverage"] >= 0.50).sum())
    n_nov = int(df["qa_any_worldpop_no_valid_pixels"].sum())
    n_poly = int((df["nex_method"] == "polygon_reducer").sum())
    n_fb = int((df["nex_method"] == "representative_point_fallback").sum())
    n_unres = int(df["nex_unresolved_null_row_count"].sum())
    n_models = int(df["nex_model_count_effective_min"].unique()[0])
    n_sw = int(df["nex_scenario_window_count"].unique()[0])
    ai_scale = cfg.get("ai_scale_factor", "")
    n_excluded = int(cfg.get("excluded_identifiers", len(excluded)))

    reasons = OrderedDict()
    for _, r in excluded.iterrows():
        reasons.setdefault(r["decision_reason"], []).append(r["OasisID"])
    excl_lines = []
    for reason, ids in reasons.items():
        excl_lines.append(f"{len(ids)} under {reason}: " + ", ".join(sorted(ids)))
    excl_txt = " | ".join(excl_lines)
    excl_classes = sorted(set(excluded["class_label_en"]))

    rows = [
        ("Purpose",
         "Source data for the main-text figures and tables and for the "
         "Supplementary Information of the global oasis exposure analysis. Every "
         "sheet is regenerated from the public release inputs by "
         "scripts/build_source_data_workbook.py."),
        ("Baseline identifier",
         f"{baseline}. Every record in this workbook carries this baseline; no "
         f"value from any earlier baseline is mixed in."),
        ("Study population",
         f"{n:,} fixed 2020 oasis polygons identified by OasisID. Class "
         f"composition: BWh {bwh:,}; BWk {bwk:,}; mixed BWh/BWk {mixed:,}; "
         f"non-BW {nonbw:,}. Total geodesic polygon area {total_area:,.6f} km2."),
        ("Excluded identifiers",
         f"{n_excluded} identifiers were removed from the earlier "
         f"{n + n_excluded:,}-polygon population: {excl_txt}. All {n_excluded} "
         f"belong to the {', '.join(excl_classes)} class, so none of the 31 "
         f"BWh-versus-BWk comparisons is affected: the BWh ({bwh:,}) and BWk "
         f"({bwk:,}) denominators are unchanged. These identifiers appear "
         f"nowhere else in this workbook; every polygon-level sheet has exactly "
         f"{n:,} rows and none of them."),
        ("Primary comparison",
         f"BWh oases minus BWk oases: BWh (n = {bwh:,}) minus BWk (n = {bwk:,}); "
         f"{strict:,} polygons in the strict contrast. Release code for this "
         f"comparison: {est['comparison'].unique()[0]}."),
        ("Median definition",
         "The patch-median estimator behind Table2_Estimands takes the lower of "
         "the two central values for an even class size. Columns that mirror "
         "that estimator are named estimand_median_* and state the definition in "
         "an adjacent column; descriptive figure statistics elsewhere in this "
         "workbook use the ordinary linear-interpolation median. The two "
         "definitions are never mixed inside one column."),
        ("Estimand set",
         f"{len(est)} primary estimands across {est['domain'].nunique()} domains "
         f"({domain_txt}). Table2_Estimands is a one-to-one copy of "
         f"data/primary_estimands_31.csv."),
        ("Inference",
         f"{cfg.get('primary_block_km', '')} km occupied-block spatial bootstrap "
         f"over {b500} occupied blocks in the strict contrast. "
         f"{'; '.join(str(s) for s in cfg.get('sensitivity_block_km', []))} km "
         f"blocks ({b250} and {b1000} occupied blocks) are reported as scale "
         f"sensitivity checks in SuppTableS8_ScaleSensitivity."),
        ("Multiple testing", str(cfg.get("multiple_testing", ""))),
        ("Support rule",
         "Applied to every estimand and reproduced at build time in "
         "Table2_Estimands (support_class_recomputed must equal support_class): "
         + SUPPORT_RULE_TEXT),
        ("Support tally", f"{support_txt}."),
        ("Uncertainty",
         "Inter-model dispersion and spatial-block intervals are different "
         "quantities and are never combined. Only spatial-block intervals are "
         "reported here; per-model values are not redistributed, so no "
         "inter-model interquartile range can be computed from this release."),
        ("Thermal stress denominator",
         f"{n_full:,} polygons have a complete 30-year UTCI record; {n_d15} "
         f"polygons with fewer valid years are RETAINED under the effective-"
         f"valid-year (D15) rule, giving {n_full + n_d15:,} valid polygons. The "
         f"{n_d15} retained polygons are listed in SuppTableS6_UTCI_D15. A "
         f"complete-30-year-only variant is reported as a sensitivity "
         f"denominator in Table1_Denominators."),
        ("Aridity and evaporative demand",
         f"Aridity Index, ET0 and ET0 standard deviation are extracted with true "
         f"polygon-cell overlap after geometry repair; all {n:,} polygons are "
         f"valid, so no polygon falls outside the aridity validity rule. Raw "
         f"Aridity Index values are scaled by {ai_scale}."),
        ("Future population",
         f"Coverage-aware descriptive scenario exposure only. {n_cov:,} polygons "
         f"have coverage above zero, {n_cov50:,} have coverage of at least 0.50, "
         f"and {n_nov} have no valid pixels in at least one scenario-year. The "
         f"{n_nov} no-valid polygons are not estimable and are excluded from "
         f"every coverage-aware total; they are flagged per row in "
         f"Figure7_Polygon by included_in_coverage_aware_totals = FALSE and are "
         f"never treated as zero population."),
        ("Future climate",
         f"Fixed-boundary tasmax, tasmin and precipitation change relative to "
         f"1995-2014, from a {n_models}-model ensemble across {n_sw} "
         f"scenario-window combinations. {n_poly:,} polygons use the polygon "
         f"reducer and {n_fb} use a deterministic nearest-valid representative-"
         f"point fallback; {n_unres} remain unresolved. Figure8_Summary reports "
         f"one scenario-window combination and now names it in explicit "
         f"scenario and window columns."),
        ("Economy and night lights",
         "Gross domestic product totals and per-capita values are in 2017 "
         "international dollars at purchasing power parity, as stated by the "
         "unit field of data/primary_estimands_31.csv. Column names carrying "
         "'2021' in earlier workbook versions were wrong and have been "
         "corrected. Night-light radiance and lit-area fraction are exposure "
         "proxies, not measures of economic output."),
        ("Geometry",
         "Oasis boundary geometries are not redistributed in this release, and "
         "no coordinate field exists in the released analysis input. Geometry is "
         "available from the published oasis boundary dataset "
         "(doi:10.3974/geodp.2025.03.01); OasisID values are stable and join "
         "directly to it."),
        ("Third-party products",
         "No third-party raster or NetCDF source file is redistributed. "
         "Provider, version, access route, citation and licence terms are listed "
         "in SuppTableS13_ProductBoundary; product roles and validity boundaries "
         "are in SuppTableS7_Products."),
        ("Missing values",
         "Blank cells indicate values that are not estimable under the stated "
         "module-specific validity rule. Blanks are not zeros. Structurally "
         "empty groups are omitted rather than zero-filled; genuine zero counts "
         "are written as explicit zeros, including the empty largest-area bin of "
         "the non-BW class in Figure3_AreaBins."),
        ("Units",
         "Degrees Celsius (\u00b0C) for temperature change, millimetres per year "
         "for annual water fluxes, millimetres per day for precipitation change, "
         "days per year for thermal stress, persons and persons per square "
         "kilometre for population, square kilometres for area, nW cm-2 sr-1 for "
         "night-light radiance. Unit strings inside the sheets are written in "
         "ASCII (for example mm yr-1 rather than mm\u00b7yr\u207b\u00b9) so that "
         "they survive any downstream text pipeline. Per-field units are in "
         "Data_Dictionary."),
        ("Sheets in this workbook", f"{len(sheet_names)}: " + "; ".join(sheet_names)),
    ]

    for name, why in dropped_notes:
        rows.append((f"Sheet removed: {name}", why))
    for sheet, col, why in omitted_notes:
        rows.append((f"Column omitted: {sheet}.{col}", why))

    rows.append(
        ("Figure and table numbering",
         "Sheet names follow the figure and table numbering of the previous "
         "workbook version. The repository deliberately contains no manuscript "
         "and no figure-building code, so this build cannot verify the numbering "
         "against the current manuscript. Confirm the mapping before release.")
    )
    rows.append(
        ("Regeneration",
         "python scripts/build_source_data_workbook.py --evidence-dir <path to "
         "the sensitivity evidence pack>. The build reads only the release "
         "inputs plus the locked 250 and 1,000 km intervals of that pack, "
         "recomputes every value, hard-codes no number it cannot derive, and "
         "fails loudly if any cross-check disagrees. The evidence pack is not "
         "redistributed and no path to it is stored in this repository.")
    )
    return pd.DataFrame(rows, columns=["Item", "Description"])


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument(
        "--evidence-dir",
        default=os.environ.get(EVIDENCE_DIR_ENV),
        help=(
            "Directory holding the sensitivity evidence pack. Required; may also "
            f"be supplied through the {EVIDENCE_DIR_ENV} environment variable."
        ),
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    if not args.evidence_dir:
        ap.error(
            "the locked 250/1,000 km intervals come from the sensitivity "
            "evidence pack, which is not part of this release. Pass "
            f"--evidence-dir or set {EVIDENCE_DIR_ENV}."
        )

    repo = Path(args.repo)
    ev = Path(args.evidence_dir)
    if not (ev / "T9_scale_250_1000_locked_vs_reproduced.csv").exists():
        ap.error(f"T9_scale_250_1000_locked_vs_reproduced.csv not found under {ev}")
    out = Path(args.out)

    df = pd.read_csv(repo / "data" / "analysis_input_minimal.csv", low_memory=False)
    est = pd.read_csv(repo / "data" / "primary_estimands_31.csv")
    cfg_est = pd.read_csv(repo / "config" / "estimands_31.csv")
    released_dd = pd.read_csv(repo / "data" / "data_dictionary.csv")
    manifest = pd.read_csv(repo / "data" / "source_product_manifest_current.csv")
    boundary = pd.read_csv(repo / "data" / "third_party_product_boundary.csv")
    cfg = read_analysis_yml(repo / "config" / "analysis.yml")

    t9 = read_csv_any(ev / "T9_scale_250_1000_locked_vs_reproduced.csv")
    excluded = read_csv_any(ev / "S3b_six_excluded_oases.csv")[
        ["OasisID", "continent5", "exact_background_class", "class_label_en",
         "admin0_dominant_name", "decision_reason"]
    ]

    # ---- structural preconditions -------------------------------------
    declared_n = int(cfg["analysis_population"])
    if len(df) != declared_n:
        raise AssertionError(
            f"analysis input has {len(df)} rows but config declares {declared_n}"
        )
    if len(est) != int(cfg["estimands"]):
        raise AssertionError("primary estimand count does not match config")
    if df["OasisID"].duplicated().any():
        raise AssertionError("duplicate OasisID in the analysis input")
    excluded_ids = set(excluded["OasisID"])
    if excluded_ids & set(df["OasisID"]):
        raise AssertionError("an excluded identifier is present in the analysis input")
    if len(excluded_ids) != int(cfg["excluded_identifiers"]):
        raise AssertionError("excluded identifier count does not match config")

    classes = class_frame(df)
    continents = continent_order(df)

    sheets: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
    sheets["Figure2_Polygon"] = build_figure2_polygon(df)
    sheets["Figure2_Summary"] = build_figure2_summary(df, classes)
    sheets["Figure3_Polygon"] = build_figure3_polygon(df)
    sheets["Figure3_ClassSummary"] = build_figure3_classsummary(df, classes)
    sheets["Figure3_AreaBins"] = build_figure3_areabins(df, classes)
    sheets["Figure4_Polygon"] = build_figure4_polygon(df)
    sheets["Figure4_Summary"] = build_figure4_summary(df, classes)
    sheets["Figure5_Polygon"] = build_figure5_polygon(df)
    sheets["Figure5_ClassSummary"] = build_figure5_classsummary(df, classes)
    sheets["Figure6_Polygon"] = build_figure6_polygon(df)
    sheets["Figure6_A_Points"] = build_figure6_a_points(df, classes, continents)
    sheets["Figure6_A_ClassMeans"] = build_figure6_a_classmeans(df, classes)
    sheets["Figure6_B_Thresholds"] = build_figure6_b_thresholds(df, classes)
    sheets["Figure6_C_OasisIQR"] = build_figure6_c_oasisiqr(df, classes)
    sheets["Figure7_Polygon"] = build_figure7_polygon(df)
    sheets["Figure7_ClassSummary"] = build_figure7_classsummary(df, classes)
    sheets["Figure7_RegionSummary"] = build_figure7_regionsummary(df, continents)
    sheets["Figure8_Polygon"] = build_figure8_polygon(df)
    sheets["Figure8_Summary"] = build_figure8_summary(df, classes, continents)
    sheets["Table1_Denominators"] = build_table1_denominators(df)
    sheets["Table2_Estimands"] = build_table2_estimands(est)
    sheets["NumericFacts"] = build_numericfacts(df, est, classes)
    sheets["SuppTableS1_GDP"] = build_supp_s1_gdp(df, classes)
    sheets["SuppTableS5_NEX"] = build_supp_s5_nex(df)
    sheets["SuppTableS6_UTCI_D15"] = build_supp_s6_utci_d15(df)
    sheets["SuppTableS7_Products"] = manifest.copy()
    sheets["SuppTableS8_ScaleSensitivity"] = build_scale_sensitivity(df, est, t9)
    sheets["SuppTableS9_EffectiveN"] = build_effective_n(df, cfg_est)
    sheets["SuppTableS10_SpatialBlocks"] = build_spatial_blocks(df, classes)
    sheets["SuppTableS13_ProductBoundary"] = boundary.copy()
    sheets["SuppTableS14_FuturePopCoverage"] = build_futurepop_coverage(df, classes)
    sheets["SuppFigS1_Polygon"] = build_suppfig_s1_polygon(df)
    sheets["SuppFigS1_ClassSummary"] = build_suppfig_s1_classsummary(df, classes)

    # ---- the economic/night-light class medians must reproduce the
    #      released estimands they claim to back --------------------------
    s1c = sheets["SuppFigS1_ClassSummary"].set_index("exact_background_class")
    est_by_id = est.set_index("fact_id")
    median_links = [
        ("F04-PRIMARY-26", "estimand_median_gdp_total_2017_int_usd"),
        ("F04-PRIMARY-27", "estimand_median_gdp_per_capita_2017_int_usd"),
        ("F04-PRIMARY-28", "estimand_median_viirs_mean_radiance"),
        ("F04-PRIMARY-29", "estimand_median_viirs_lit_area_fraction"),
    ]
    for fact_id, col in median_links:
        a = float(s1c.loc["BWh_background", col])
        b = float(s1c.loc["BWk_background", col])
        if not np.isclose(a, float(est_by_id.loc[fact_id, "estimate_bwh"]), rtol=1e-12,
                          atol=0):
            raise AssertionError(f"{col} BWh does not match {fact_id} estimate_bwh")
        if not np.isclose(b, float(est_by_id.loc[fact_id, "estimate_bwk"]), rtol=1e-12,
                          atol=0):
            raise AssertionError(f"{col} BWk does not match {fact_id} estimate_bwk")
        if not np.isclose(np.log(a / b),
                          float(est_by_id.loc[fact_id, "effect_bwh_minus_bwk"]),
                          rtol=1e-12, atol=0):
            raise AssertionError(f"{col} log ratio does not reproduce {fact_id}")

    # ---- optional cross-checks against the evidence pack ---------------
    crosschecks = ["SuppFigS1_ClassSummary class medians reproduce "
                   "F04-PRIMARY-26 through -29"]
    t1_path = ev / "T1_effective_n_per_estimand.csv"
    if t1_path.exists():
        t1 = read_csv_any(t1_path)
        mine = sheets["SuppTableS9_EffectiveN"]
        for col in ["class_total_bwh", "class_total_bwk", "effective_n_bwh",
                    "effective_n_bwk", "raw_nan_bwh", "raw_nan_bwk",
                    "zero_valued_bwh", "zero_valued_bwk"]:
            a = mine.set_index("fact_id")[col]
            b = t1.set_index("fact_id")[col]
            if not a.reindex(b.index).equals(b):
                raise AssertionError(f"SuppTableS9_EffectiveN disagrees with T1 on {col}")
        crosschecks.append("SuppTableS9_EffectiveN matches T1_effective_n_per_estimand")
    t2_path = ev / "T2_spatial_block_counts.csv"
    if t2_path.exists():
        t2 = read_csv_any(t2_path).set_index("scale_km")
        mine = sheets["SuppTableS10_SpatialBlocks"].set_index("scale_km")
        for scale in (250, 500, 1000):
            pairs = [
                ("blocks_strict_bwh_bwk", "blocks_strict_2564"),
                ("blocks_union_bwh_bwk", "blocks_union_BWh_BWk"),
                ("blocks_shared_bwh_bwk", "blocks_shared_BWh_BWk"),
                ("blocks_bwh_only", "blocks_BWh_only"),
                ("blocks_bwk_only", "blocks_BWk_only"),
                ("blocks_all_population", "blocks_all_3437"),
            ]
            for mine_col, t2_col in pairs:
                if int(mine.loc[scale, mine_col]) != int(t2.loc[scale, t2_col]):
                    raise AssertionError(
                        f"spatial block mismatch at {scale} km on {mine_col}"
                    )
        crosschecks.append("SuppTableS10_SpatialBlocks matches T2_spatial_block_counts")
    t3_path = ev / "T3_futurepop_coverage_by_class.csv"
    if t3_path.exists():
        t3 = read_csv_any(t3_path).set_index("class_label_en")
        mine = sheets["SuppTableS14_FuturePopCoverage"].set_index("background_class")
        for cls in t3.index:
            for col in ["futurepop_coverage__mean", "futurepop_coverage__median",
                        "futurepop_coverage__n_eq0", "futurepop_coverage__n_lt050",
                        "futurepop_coverage__n_ge099"]:
                if not np.isclose(float(mine.loc[cls, col]), float(t3.loc[cls, col])):
                    raise AssertionError(
                        f"futurepop coverage mismatch for {cls} on {col}"
                    )
        crosschecks.append("SuppTableS14_FuturePopCoverage matches T3_futurepop_coverage_by_class")

    # ---- documentation of what was removed and why ---------------------
    dropped_notes = [
        ("SuppTableS2_Denoms",
         "Was a byte-identical duplicate of Table1_Denominators. Duplicated "
         "denominator tables drift apart; the Supplementary Information should "
         "cite Table1_Denominators instead."),
        ("SuppTableS3_Estimands",
         "Was a byte-identical duplicate of Table2_Estimands. Cite "
         "Table2_Estimands from the Supplementary Information instead."),
        ("SuppTableS4_FuturePop",
         "Was a byte-identical duplicate of Figure7_ClassSummary. It is replaced "
         "by SuppTableS14_FuturePopCoverage, which carries the genuinely new "
         "per-class coverage distribution."),
        ("SuppTableS11_NEX_ModelIQR",
         "Not created. An inter-model interquartile range cannot be derived from "
         "this release: the analysis input carries only the ensemble median plus "
         "model-count audit fields, and per-model values are not redistributed. "
         "The claim of interquartile model dispersion was therefore removed from "
         "SuppTableS5_NEX rather than backed with a number the release cannot "
         "support."),
        ("SuppTableS12_ExcludedOases",
         "Not created as a data sheet. The excluded identifiers and their "
         "reasons are recorded once, in this README sheet, and appear in no "
         "data sheet of the workbook."),
    ]
    omitted_notes = [
        ("Figure2_Polygon", "representative_longitude_deg_e",
         "No coordinate, centroid or geometry field exists anywhere in the "
         "released analysis input, and the release deliberately excludes oasis "
         "boundary geometries. Representative points from the superseded "
         "3,443-polygon geometry set must not be carried over. Use the published "
         "oasis boundary dataset (doi:10.3974/geodp.2025.03.01), joined on "
         "OasisID."),
        ("Figure2_Polygon", "representative_latitude_deg_n",
         "Same reason as representative_longitude_deg_e."),
        ("Figure2_Summary", "color_hex",
         "A figure-design constant, not a measured quantity, and not derivable "
         "from any release input. This build hard-codes no value it cannot "
         "derive, so the column is omitted; take the palette from the current "
         "figure specification when the figure is drawn."),
        ("SuppTableS5_NEX", "interquartile model dispersion",
         "Removed from the interpretation text of the statistic row. See the "
         "SuppTableS11_NEX_ModelIQR entry above."),
    ]

    renames = {
        ("SuppFigS1_Polygon", "gdp2020_per_capita_2017_int_usd_area_mean"):
            "gdp2020_pc_ppp2021_int_usd_area_mean",
        ("SuppFigS1_Polygon",
         "gdp2020_total_analysis_per_ghsl_pop2020_2017_int_usd_per_person"):
            "gdp2020_total_analysis_per_ghsl_pop2020",
        ("Figure2_Polygon", "polygon_area_km2"): "polygon_area_km2_geodesic",
        ("Figure3_Polygon", "polygon_area_km2"): "polygon_area_km2_geodesic",
        ("Figure4_Polygon", "polygon_area_km2"): "polygon_area_km2_geodesic",
        ("Figure5_Polygon", "polygon_area_km2"): "polygon_area_km2_geodesic",
        ("Figure7_Polygon", "polygon_area_km2"): "polygon_area_km2_geodesic",
        ("Figure2_Polygon", "continent"): "continent5",
        ("Figure5_Polygon", "aridity_index"): "ai_scaled",
        ("Figure5_Polygon", "et0_mm_yr"): "et0_v31_yr_raw_area_weighted_mean_raw",
        ("Figure5_Polygon", "et0_sd_mm_yr"): "et0_v31_yr_sd_raw_area_weighted_mean_raw",
        ("Figure4_Polygon", "ghsl_population_2020_persons"): "pop_sum_2020",
        ("Figure6_Polygon", "ghsl_population_2020_persons"): "pop_sum_2020",
        ("Figure8_Polygon", "extraction_method"): "nex_method",
        ("Figure7_Polygon", "no_valid_pixels_any_scenario"):
            "qa_any_worldpop_no_valid_pixels",
    }

    ordered_names = ["README", "Data_Dictionary"] + list(sheets.keys())
    readme = build_readme(df, est, cfg, excluded, classes, dropped_notes,
                          omitted_notes, ordered_names)
    dictionary = build_data_dictionary(sheets, cfg_est, released_dd, renames)

    final: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
    final["README"] = readme
    final["Data_Dictionary"] = dictionary
    final.update(sheets)

    # ---- final invariants ---------------------------------------------
    polygon_sheets = [k for k in final if k.endswith("_Polygon")]
    for name in polygon_sheets:
        if len(final[name]) != declared_n:
            raise AssertionError(f"{name} has {len(final[name])} rows, expected {declared_n}")
    for name, frame in final.items():
        if name == "README":
            continue
        for col in frame.columns:
            if frame[col].dtype == object or str(frame[col].dtype).startswith("str"):
                hit = frame[col].astype(str).isin(excluded_ids)
                if hit.any():
                    raise AssertionError(f"excluded identifier found in {name}.{col}")
    if len(final["Table2_Estimands"]) != int(cfg["estimands"]):
        raise AssertionError("Table2_Estimands row count is wrong")
    if len(final["SuppTableS8_ScaleSensitivity"]) != int(cfg["estimands"]):
        raise AssertionError("SuppTableS8_ScaleSensitivity row count is wrong")

    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        for name, frame in final.items():
            if len(name) > 31:
                raise AssertionError(f"sheet name too long for Excel: {name}")
            frame.to_excel(xw, sheet_name=name, index=False)

    print(f"wrote {out}")
    print(f"{len(final)} sheets, population {declared_n}, estimands {len(est)}")
    for c in crosschecks:
        print("cross-check OK:", c)
    for name, frame in final.items():
        print(f"  {name}: {len(frame)} rows x {len(frame.columns)} cols")
    return 0


if __name__ == "__main__":
    sys.exit(main())
