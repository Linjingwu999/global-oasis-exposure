from __future__ import annotations

import re

import pandas as pd


BLOCK_SCALES = (250, 500, 1000)


def parse_block_id(value: str, scale_km: int) -> tuple[int, int]:
    pattern = rf"EE8857_{scale_km}km_(-?\d+)_(-?\d+)"
    match = re.fullmatch(pattern, value)
    if match is None:
        raise ValueError(f"Invalid {scale_km}-km block identifier: {value}")
    return int(match.group(1)), int(match.group(2))


def validate_block_mapping(data: pd.DataFrame) -> dict[str, object]:
    required = {f"block_{scale}km" for scale in BLOCK_SCALES}
    missing = sorted(required - set(data.columns))
    if missing:
        raise KeyError(f"Missing spatial-block columns: {missing}")
    parsed: dict[int, list[tuple[int, int]]] = {}
    for scale in BLOCK_SCALES:
        column = f"block_{scale}km"
        if data[column].isna().any():
            raise ValueError(f"Null values found in {column}")
        parsed[scale] = [parse_block_id(str(value), scale) for value in data[column]]

    hierarchy_failures = 0
    for block_250, block_500, block_1000 in zip(
        parsed[250], parsed[500], parsed[1000], strict=True
    ):
        expected_500 = (block_250[0] // 2, block_250[1] // 2)
        expected_1000 = (block_500[0] // 2, block_500[1] // 2)
        if block_500 != expected_500 or block_1000 != expected_1000:
            hierarchy_failures += 1
    if hierarchy_failures:
        raise ValueError(f"Spatial-block hierarchy failures: {hierarchy_failures}")
    strict = data["class_label_en"].isin(("BWh oases", "BWk oases"))
    return {
        "row_count": int(len(data)),
        "hierarchy_failures": 0,
        "occupied_all": {
            str(scale): int(data[f"block_{scale}km"].nunique()) for scale in BLOCK_SCALES
        },
        "occupied_strict_bwh_bwk": {
            str(scale): int(data.loc[strict, f"block_{scale}km"].nunique())
            for scale in BLOCK_SCALES
        },
    }
