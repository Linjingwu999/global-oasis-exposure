from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .estimands import group_statistic, method_weights, point_result


def stable_seed(run_key: str, base_seed: int = 20260710) -> int:
    digest = hashlib.sha256(f"{base_seed}:{run_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def _write_checkpoint(
    path: Path,
    effects: list[float],
    attempts: int,
    invalid: int,
    metadata: dict[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    try:
        with open(temporary, "wb") as handle:
            np.savez_compressed(
                handle,
                effects=np.asarray(effects, dtype=float),
                attempts=np.asarray(attempts, dtype=np.int64),
                invalid=np.asarray(invalid, dtype=np.int64),
                metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _load_checkpoint(
    path: Path | None,
    expected_metadata: dict[str, object],
    target_valid: int,
    resume: bool,
) -> tuple[list[float], int, int]:
    if not resume or path is None or not path.exists():
        return [], 0, 0
    try:
        with np.load(path, allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata_json"].item()))
            if metadata != expected_metadata:
                return [], 0, 0
            effects = payload["effects"].astype(float).tolist()[:target_valid]
            attempts = int(payload["attempts"].item())
            invalid = int(payload["invalid"].item())
            return effects, attempts, invalid
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return [], 0, 0


def _sample_fingerprint(
    sample: pd.DataFrame, source_field: str, method: str, block_column: str
) -> str:
    columns = ["class_label_en", source_field, block_column]
    if "OasisID" in sample:
        columns.insert(0, "OasisID")
    if method == "area_weighted_mean_difference":
        columns.append("area_km2")
    if method == "population_weighted_mean_difference":
        columns.append("pop_2020_ghsl")
    row_hashes = pd.util.hash_pandas_object(sample[columns], index=False).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest().upper()


def cluster_bootstrap(
    sample: pd.DataFrame,
    contract_row: Mapping[str, object],
    *,
    scale_km: int,
    target_valid: int,
    run_key: str,
    base_seed: int = 20260710,
    checkpoint: Path | None = None,
    resume: bool = False,
) -> dict[str, object]:
    """Run the occupied-block bootstrap used by the locked analysis.

    The default repository verifier does not call this function. It is exposed
    so the inferential procedure is inspectable and reusable without silently
    replacing the locked 2,000-replicate outputs.
    """
    block_column = f"block_{scale_km}km"
    if block_column not in sample:
        raise KeyError(block_column)
    source_field = str(contract_row["source_field"])
    method = str(contract_row["implementation_method"])
    values = pd.to_numeric(sample[source_field], errors="coerce").to_numpy(float)
    groups = sample["class_label_en"].astype(str).to_numpy()
    base_weights = method_weights(sample, method)
    block_codes, occupied_blocks = pd.factorize(sample[block_column].astype(str), sort=True)
    block_count = len(occupied_blocks)
    if block_count < 2:
        raise ValueError("At least two occupied spatial blocks are required")

    seed = stable_seed(run_key, base_seed)
    checkpoint_metadata = {
        "run_key": run_key,
        "scale_km": scale_km,
        "target_valid": target_valid,
        "seed": seed,
        "occupied_blocks": block_count,
        "source_field": source_field,
        "implementation_method": method,
        "sample_sha256": _sample_fingerprint(sample, source_field, method, block_column),
    }
    effects, attempts, invalid = _load_checkpoint(
        checkpoint, checkpoint_metadata, target_valid, resume
    )
    rng = np.random.default_rng(seed)
    if attempts:
        rng.integers(0, block_count, size=(attempts, block_count), endpoint=False)
    max_attempts = max(int(math.ceil(target_valid / 0.90)), target_valid + 250)
    while len(effects) < target_valid and attempts < max_attempts:
        draws = rng.integers(0, block_count, size=block_count, endpoint=False)
        multipliers = np.bincount(draws, minlength=block_count).astype(float)
        effect, _, _, _ = group_statistic(
            values,
            groups,
            method,
            base_weights * multipliers[block_codes],
        )
        attempts += 1
        if np.isfinite(effect):
            effects.append(float(effect))
        else:
            invalid += 1
        if checkpoint is not None and len(effects) and (
            len(effects) % 250 == 0 or len(effects) == target_valid
        ):
            _write_checkpoint(
                checkpoint,
                effects,
                attempts,
                invalid,
                checkpoint_metadata,
            )
    if len(effects) < target_valid:
        raise RuntimeError(
            f"Valid bootstrap repeats={len(effects)}/{target_valid}; "
            f"attempts={attempts}; invalid={invalid}"
        )
    array = np.asarray(effects[:target_valid], dtype=float)
    ci_low, ci_high = np.quantile(array, [0.025, 0.975])
    first_count = min(1000, len(array))
    ci1000_low, ci1000_high = np.quantile(array[:first_count], [0.025, 0.975])
    p_lower = (np.count_nonzero(array <= 0) + 1) / (len(array) + 1)
    p_upper = (np.count_nonzero(array >= 0) + 1) / (len(array) + 1)
    ci_supports_nonzero = bool(ci_low > 0 or ci_high < 0)
    ci1000_supports_nonzero = bool(ci1000_low > 0 or ci1000_high < 0)
    return {
        **point_result(sample, contract_row),
        "run_key": run_key,
        "scale_km": scale_km,
        "seed": seed,
        "occupied_blocks": block_count,
        "bootstrap_valid_replicates": len(array),
        "bootstrap_attempts": attempts,
        "bootstrap_invalid_attempts": invalid,
        "ci95_low": float(ci_low),
        "ci95_high": float(ci_high),
        "ci1000_low": float(ci1000_low),
        "ci1000_high": float(ci1000_high),
        "ci_supports_nonzero": ci_supports_nonzero,
        "ci1000_supports_nonzero": ci1000_supports_nonzero,
        "convergence_status": (
            "stable"
            if ci_supports_nonzero == ci1000_supports_nonzero
            else "support_changed_1000_to_full"
        ),
        "p_two_sided": min(1.0, 2.0 * min(p_lower, p_upper)),
    }
