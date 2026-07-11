from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


NEX_FIELDS = [
    f"nex_{scenario}_{window}_{variable}_delta_1995_2014_median"
    for scenario in ("ssp245", "ssp585")
    for window in ("2041_2070", "2071_2099")
    for variable in ("tasmax", "tasmin", "pr")
]

SELECTED_FIELDS = [
    "OasisID",
    "class_label_en",
    "continent5",
    "area_km2",
    "block_250km",
    "block_500km",
    "block_1000km",
    "ghsl_qc",
    "ai_qc",
    "terraclimate_qc",
    "jrc_qc",
    "utci_qc",
    "nex_qc",
    "nex_method",
    "futurepop_coverage",
    "pop_2020_ghsl",
    "pop_density_per_km2_polygon_area",
    "built_s_share_of_polygon_area",
    "ai_scaled",
    "terraclimate_def_1991_2020_mean_annual_mm",
    "ever_water_fraction",
    "utci_mean_annual_days_max_ge_32c",
    "utci_mean_annual_days_min_le_minus13c",
    *NEX_FIELDS,
    "pop_ssp2_2050",
    "pop_ssp2_2080",
    "pop_ssp5_2050",
    "pop_ssp5_2080",
    "et0_qc",
    "et0_v31_yr_raw_valid_pixel_count",
    "et0_v31_yr_raw_area_weighted_mean_raw",
    "et0_v31_yr_sd_raw_valid_pixel_count",
    "et0_v31_yr_sd_raw_area_weighted_mean_raw",
]


def build_minimum_input(
    unified_path: Path, block_mapping_path: Path, output_path: Path
) -> pd.DataFrame:
    unified = pd.read_csv(unified_path, low_memory=False)
    blocks = pd.read_csv(block_mapping_path, low_memory=False)
    block_fields = ["OasisID", "block_250km", "block_500km", "block_1000km"]
    joined = unified.merge(
        blocks[block_fields], on="OasisID", how="left", validate="one_to_one"
    )
    missing = sorted(set(SELECTED_FIELDS) - set(joined.columns))
    if missing:
        raise KeyError(f"Required fields are missing: {missing}")
    minimum = joined[SELECTED_FIELDS].copy()
    if len(minimum) != 3443 or minimum["OasisID"].nunique() != 3443:
        raise ValueError("Expected exactly 3,443 unique oasis identifiers")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    minimum.to_csv(output_path, index=False, lineterminator="\n")
    return minimum


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the minimum author-derived analysis table from approved local inputs."
    )
    parser.add_argument("--unified", type=Path, required=True)
    parser.add_argument("--block-mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frame = build_minimum_input(args.unified, args.block_mapping, args.output)
    print(f"WROTE: {len(frame)} rows x {len(frame.columns)} columns")


if __name__ == "__main__":
    main()
