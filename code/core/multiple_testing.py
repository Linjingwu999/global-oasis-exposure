from __future__ import annotations

import numpy as np
import pandas as pd


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = pd.to_numeric(p_values, errors="coerce").dropna()
    if valid.empty:
        return result
    ordered = valid.sort_values()
    count = len(ordered)
    raw = ordered.to_numpy(float) * count / np.arange(1, count + 1, dtype=float)
    adjusted = np.minimum.accumulate(raw[::-1])[::-1]
    result.loc[ordered.index] = np.minimum(adjusted, 1.0)
    return result
