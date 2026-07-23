from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .bootstrap import cluster_bootstrap
from .estimands import point_result, sample_for_estimand
from .io_utils import atomic_bytes, atomic_csv, atomic_json, sha256
from .multiple_testing import benjamini_hochberg


ALTERNATIVE_METHODS = {
    "ghsl_density_patch_median_log_ratio": "area_weighted_mean_difference",
    "ghsl_built_share_patch_median_difference": "area_weighted_mean_difference",
    "ai_area_weighted_mean_difference": "median_difference",
    "terraclimate_def_area_weighted_mean_difference": "median_difference",
    "jrc_ever_water_fraction_area_weighted_mean_difference": "median_difference",
    "utci_heat_ge32_patch_median_difference": "population_weighted_mean_difference",
    "utci_cold_le_minus13_patch_median_difference": "population_weighted_mean_difference",
}
AREA_LONG_TAIL_ESTIMANDS = {
    "ai_area_weighted_mean_difference",
    "terraclimate_def_area_weighted_mean_difference",
    "jrc_ever_water_fraction_area_weighted_mean_difference",
}


def _run_fingerprint(
    data: pd.DataFrame, contract: pd.DataFrame, parameters: dict[str, int]
) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(data, index=False).to_numpy().tobytes())
    digest.update(contract.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    digest.update(json.dumps(parameters, sort_keys=True).encode("utf-8"))
    implementation_files = [
        Path(__file__),
        *[
            Path(__file__).with_name(name)
            for name in ("bootstrap.py", "estimands.py", "io_utils.py", "multiple_testing.py")
        ],
    ]
    for path in implementation_files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    digest.update(
        json.dumps(
            {
                "python": sys.version,
                "numpy": np.__version__,
                "pandas": pd.__version__,
            },
            sort_keys=True,
        ).encode("utf-8")
    )
    return digest.hexdigest().upper()


def _append_log(path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_bytes(path, f"{existing}{timestamp} {message}\n".encode("utf-8"))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def _same_direction(left: float, right: float) -> bool:
    return bool(np.sign(left) == np.sign(right))


def run_full_inference(
    data: pd.DataFrame,
    contract: pd.DataFrame,
    output_dir: Path,
    *,
    locked_primary: pd.DataFrame | None = None,
    resume: bool = False,
    base_seed: int = 20260710,
    primary_replicates: int = 2000,
    primary_extension_replicates: int = 5000,
    sensitivity_replicates: int = 1000,
    sensitivity_extension_replicates: int = 2000,
) -> dict[str, Any]:
    """Run the complete primary and support-class orchestration.

    This is opt-in because the release integrity check
    approved locked inference and must not silently replace it.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    parameters = {
        "base_seed": base_seed,
        "primary_replicates": primary_replicates,
        "primary_extension_replicates": primary_extension_replicates,
        "sensitivity_replicates": sensitivity_replicates,
        "sensitivity_extension_replicates": sensitivity_extension_replicates,
    }
    fingerprint = _run_fingerprint(data, contract, parameters)
    state_path = output_dir / "inference_state.json"
    log_path = output_dir / "inference.log"
    state: dict[str, Any] | None = None
    if resume and state_path.exists():
        try:
            candidate = json.loads(state_path.read_text(encoding="utf-8"))
            if candidate.get("run_fingerprint") == fingerprint:
                state = candidate
        except (OSError, json.JSONDecodeError):
            state = None
    if state is None:
        state = {
            "status": "running",
            "run_fingerprint": fingerprint,
            "parameters": parameters,
            "runs": {},
            "outputs": {},
        }
        atomic_bytes(log_path, b"")
    state["status"] = "running"
    atomic_json(state_path, state)
    _append_log(log_path, f"full inference running resume={resume}")
    failures: list[dict[str, str]] = []

    def bootstrap_run(
        run_id: str,
        run_key: str,
        row: dict[str, object],
        sample: pd.DataFrame,
        scale_km: int,
        target_valid: int,
    ) -> dict[str, object] | None:
        safe_id = _safe_name(run_id)
        result_path = output_dir / "run_results" / f"{safe_id}.json"
        checkpoint = output_dir / "checkpoints" / f"{safe_id}.npz"
        record = state["runs"].setdefault(run_id, {"status": "pending"})
        if (
            resume
            and record.get("status") == "success"
            and result_path.is_file()
            and record.get("result_sha256") == sha256(result_path)
        ):
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                _append_log(log_path, f"run resumed {run_id}")
                return result
            except (OSError, json.JSONDecodeError):
                pass
        record.update({"status": "running", "run_key": run_key})
        atomic_json(state_path, state)
        _append_log(log_path, f"run running {run_id}")
        try:
            result = cluster_bootstrap(
                sample,
                row,
                scale_km=scale_km,
                target_valid=target_valid,
                run_key=run_key,
                base_seed=base_seed,
                checkpoint=checkpoint,
                resume=resume,
            )
            atomic_json(result_path, result)
            record.update(
                {
                    "status": "success",
                    "result_sha256": sha256(result_path),
                    "error": None,
                }
            )
            atomic_json(state_path, state)
            _append_log(log_path, f"run success {run_id}")
            return result
        except Exception as exc:
            record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            failures.append({"run": run_id, "error": str(exc)})
            atomic_json(state_path, state)
            _append_log(log_path, f"run failed {run_id} {type(exc).__name__}: {exc}")
            return None

    primary_rows: list[dict[str, object]] = []
    primary_by_estimand: dict[str, dict[str, object]] = {}
    contract_records = contract.to_dict("records")
    for row in contract_records:
        domain = str(row["domain"])
        estimand = str(row["estimand"])
        run_key = f"main__{domain}__{estimand}__500km"
        try:
            sample = sample_for_estimand(data, row, scale_km=500)
        except Exception as exc:
            failures.append({"run": run_key, "error": str(exc)})
            continue
        result = bootstrap_run(
            run_key, run_key, row, sample, 500, primary_replicates
        )
        if result is None:
            continue
        if result["convergence_status"] == "support_changed_1000_to_full":
            extended = bootstrap_run(
                f"{run_key}__extended{primary_extension_replicates}",
                run_key,
                row,
                sample,
                500,
                primary_extension_replicates,
            )
            if extended is not None:
                result = extended
                result["convergence_status"] = (
                    f"extended_to_{primary_extension_replicates}_after_1000_primary_change"
                )
        primary = {
            **result,
            "fact_id": str(row["fact_id"]),
            "domain": domain,
            "estimand": estimand,
            "expected_support_class": str(row["support_class"]),
        }
        primary_rows.append(primary)
        primary_by_estimand[estimand] = primary

    primary_frame = pd.DataFrame(primary_rows)
    if not primary_frame.empty:
        primary_frame["fdr_q"] = primary_frame.groupby("domain", sort=False)[
            "p_two_sided"
        ].transform(benjamini_hochberg)
    atomic_csv(output_dir / "full_primary_inference.csv", primary_frame)

    sensitivity_rows: list[dict[str, object]] = []
    method_rows: list[dict[str, object]] = []
    for row in contract_records:
        estimand = str(row["estimand"])
        domain = str(row["domain"])
        primary = primary_by_estimand.get(estimand)
        if primary is None:
            continue
        for scale in (250, 1000):
            run_key = f"scale__{domain}__{estimand}__{scale}km"
            try:
                sample = sample_for_estimand(data, row, scale_km=scale)
            except Exception as exc:
                failures.append({"run": run_key, "error": str(exc)})
                continue
            result = bootstrap_run(
                run_key, run_key, row, sample, scale, sensitivity_replicates
            )
            if result is None:
                continue
            if bool(result["ci_supports_nonzero"]) != bool(
                primary["ci_supports_nonzero"]
            ):
                extended = bootstrap_run(
                    f"{run_key}__extended{sensitivity_extension_replicates}",
                    run_key,
                    row,
                    sample,
                    scale,
                    sensitivity_extension_replicates,
                )
                if extended is not None:
                    result = extended
            sensitivity_rows.append(
                {
                    **result,
                    "sensitivity_type": "spatial_block_scale",
                    "primary_estimand": estimand,
                    "direction_agrees_primary": _same_direction(
                        float(result["effect_bwh_minus_bwk"]),
                        float(primary["effect_bwh_minus_bwk"]),
                    ),
                    "support_agrees_primary": bool(result["ci_supports_nonzero"])
                    == bool(primary["ci_supports_nonzero"]),
                }
            )

        alternative_method = ALTERNATIVE_METHODS.get(estimand)
        if alternative_method:
            alternative_row = dict(row)
            alternative_row["implementation_method"] = alternative_method
            try:
                alternative = point_result(
                    sample_for_estimand(data, alternative_row, scale_km=500),
                    alternative_row,
                )
                method_rows.append(
                    {
                        **alternative,
                        "sensitivity_type": "weighting_or_aggregation",
                        "primary_estimand": estimand,
                        "direction_agrees_primary": _same_direction(
                            float(alternative["effect_bwh_minus_bwk"]),
                            float(primary["effect_bwh_minus_bwk"]),
                        ),
                    }
                )
            except Exception as exc:
                failures.append({"run": f"alternative__{estimand}", "error": str(exc)})

        if estimand in AREA_LONG_TAIL_ESTIMANDS:
            try:
                trimmed = point_result(
                    sample_for_estimand(
                        data, row, scale_km=500, remove_top_one_percent_area=True
                    ),
                    row,
                )
                method_rows.append(
                    {
                        **trimmed,
                        "sensitivity_type": "area_long_tail",
                        "primary_estimand": estimand,
                        "direction_agrees_primary": _same_direction(
                            float(trimmed["effect_bwh_minus_bwk"]),
                            float(primary["effect_bwh_minus_bwk"]),
                        ),
                    }
                )
            except Exception as exc:
                failures.append({"run": f"area_long_tail__{estimand}", "error": str(exc)})

        if domain == "nex":
            run_key = f"nex_polygon_only__{estimand}__500km"
            try:
                polygon_sample = sample_for_estimand(
                    data, row, scale_km=500, polygon_only=True
                )
            except Exception as exc:
                failures.append({"run": run_key, "error": str(exc)})
                continue
            polygon = bootstrap_run(
                run_key,
                run_key,
                row,
                polygon_sample,
                500,
                sensitivity_replicates,
            )
            if polygon is not None:
                method_rows.append(
                    {
                        **polygon,
                        "sensitivity_type": "NEX_fallback_method",
                        "primary_estimand": estimand,
                        "direction_agrees_primary": _same_direction(
                            float(polygon["effect_bwh_minus_bwk"]),
                            float(primary["effect_bwh_minus_bwk"]),
                        ),
                    }
                )

    sensitivity_frame = pd.DataFrame(sensitivity_rows)
    method_frame = pd.DataFrame(method_rows)
    atomic_csv(output_dir / "full_spatial_sensitivity.csv", sensitivity_frame)
    atomic_csv(output_dir / "full_method_sensitivity.csv", method_frame)

    support_rows: list[dict[str, object]] = []
    for primary in primary_rows:
        estimand = str(primary["estimand"])
        q_value = float(
            primary_frame.loc[primary_frame["estimand"].eq(estimand), "fdr_q"].iloc[0]
        )
        scale = sensitivity_frame.loc[
            sensitivity_frame.get("primary_estimand", pd.Series(dtype=str)).eq(estimand)
        ]
        methods = method_frame.loc[
            method_frame.get("primary_estimand", pd.Series(dtype=str)).eq(estimand)
        ]
        scale_ok = (
            len(scale) == 2
            and bool(scale["direction_agrees_primary"].all())
            and bool(scale["support_agrees_primary"].all())
        )
        method_ok = methods.empty or bool(methods["direction_agrees_primary"].all())
        if not bool(primary["ci_supports_nonzero"]) or q_value >= 0.05:
            support_class = "not_supported"
        elif scale_ok and method_ok:
            support_class = "robust"
        else:
            support_class = "sensitive"
        support_rows.append(
            {
                "fact_id": primary["fact_id"],
                "domain": primary["domain"],
                "estimand": estimand,
                "effect_bwh_minus_bwk": primary["effect_bwh_minus_bwk"],
                "n_bwh": primary["n_bwh"],
                "n_bwk": primary["n_bwk"],
                "estimate_bwh": primary["estimate_bwh"],
                "estimate_bwk": primary["estimate_bwk"],
                "ci95_low": primary["ci95_low"],
                "ci95_high": primary["ci95_high"],
                "fdr_q": q_value,
                "scale_sensitivity_agrees": scale_ok,
                "method_sensitivity_direction_agrees": method_ok,
                "support_class": support_class,
                "expected_support_class": primary["expected_support_class"],
            }
        )
    support_frame = pd.DataFrame(support_rows)
    atomic_csv(output_dir / "full_support_classification.csv", support_frame)

    comparison_failures: list[str] = []
    if locked_primary is not None and len(support_frame) == len(locked_primary):
        locked = locked_primary.set_index("estimand")
        for row in support_frame.to_dict("records"):
            expected = locked.loc[str(row["estimand"])]
            for field in (
                "estimate_bwh",
                "estimate_bwk",
                "effect_bwh_minus_bwk",
                "ci95_low",
                "ci95_high",
                "fdr_q",
            ):
                if not np.isclose(
                    float(row[field]), float(expected[field]), rtol=1e-10, atol=1e-10
                ):
                    comparison_failures.append(f"{row['estimand']}:{field}")
            for field in ("n_bwh", "n_bwk"):
                if int(row[field]) != int(float(expected[field])):
                    comparison_failures.append(f"{row['estimand']}:{field}")
            if row["support_class"] != expected["support_class"]:
                comparison_failures.append(f"{row['estimand']}:support_class")
    elif locked_primary is not None:
        comparison_failures.append("locked_primary_row_count")

    status = (
        "PASS"
        if not failures
        and not comparison_failures
        and len(primary_frame) == len(contract)
        else "FAIL"
    )
    qa = {
        "status": status,
        "run_fingerprint": fingerprint,
        "primary_estimands": len(primary_frame),
        "spatial_sensitivity_rows": len(sensitivity_frame),
        "method_sensitivity_rows": len(method_frame),
        "support_counts": support_frame["support_class"].value_counts().to_dict()
        if not support_frame.empty
        else {},
        "failures": failures,
        "locked_comparison_failures": comparison_failures,
        "nex_model_uncertainty_policy": "kept separate; not folded into spatial-block bootstrap",
    }
    atomic_json(output_dir / "full_inference_QA.json", qa)
    state["status"] = status
    state["outputs"] = {
        name: sha256(output_dir / name)
        for name in (
            "full_primary_inference.csv",
            "full_spatial_sensitivity.csv",
            "full_method_sensitivity.csv",
            "full_support_classification.csv",
            "full_inference_QA.json",
        )
    }
    _append_log(log_path, f"full inference {status}")
    state["outputs"]["inference.log"] = sha256(log_path)
    atomic_json(state_path, state)
    return qa
