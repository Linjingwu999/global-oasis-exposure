from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bootstrap import cluster_bootstrap, stable_seed
from src.estimands import sample_for_estimand
from src.inference import run_full_inference
from src.multiple_testing import benjamini_hochberg
from src.validate_release import validate_repository


class LockedOutputTests(unittest.TestCase):
    def test_full_release_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            qa = validate_repository(REPO_ROOT, Path(temporary), resume=True)
        self.assertEqual(qa["status"], "PASS")
        self.assertEqual(qa["summary"]["estimands"], 21)
        self.assertEqual(qa["summary"]["numeric_facts"], 29)
        self.assertFalse(qa["summary"]["bootstrap_recomputed"])

    def test_interrupted_validation_resumes_completed_estimators(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            validate_repository(REPO_ROOT, output, resume=True)
            state_path = output / "reproduction_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["status"] = "running"
            for name, work in state["work_packages"].items():
                if name != "point_estimands":
                    work["status"] = "pending"
                    work.pop("result_sha256", None)
            state_path.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            (output / "reproduction_QA.json").unlink()
            qa = validate_repository(REPO_ROOT, output, resume=True)
            log = (output / "reproduction.log").read_text(encoding="utf-8")
        self.assertTrue(qa["resumed"])
        self.assertEqual(qa["point_estimates"]["resumed_estimators"], 21)
        self.assertIn("point_estimand resumed F04-PRIMARY-01", log)

    def test_stable_task_seed(self) -> None:
        first = stable_seed("primary:example:500")
        self.assertEqual(first, stable_seed("primary:example:500"))
        self.assertNotEqual(first, stable_seed("primary:example:250"))

    def test_benjamini_hochberg(self) -> None:
        observed = benjamini_hochberg(pd.Series([0.01, 0.03, 0.02]))
        np.testing.assert_allclose(observed.to_numpy(), [0.03, 0.03, 0.03])

    def test_bootstrap_checkpoint_rejects_changed_fingerprint(self) -> None:
        data = pd.DataFrame(
            {
                "OasisID": ["h1", "h2", "c1", "c2"],
                "class_label_en": ["BWh oases", "BWh oases", "BWk oases", "BWk oases"],
                "pop_density_per_km2_polygon_area": [4.0, 5.0, 1.0, 2.0],
                "ghsl_qc": ["pass"] * 4,
                "area_km2": [1.0] * 4,
                "block_250km": ["EE8857_250km_0_0", "EE8857_250km_1_0", "EE8857_250km_2_0", "EE8857_250km_3_0"],
                "block_500km": ["EE8857_500km_0_0", "EE8857_500km_1_0", "EE8857_500km_2_0", "EE8857_500km_3_0"],
            }
        )
        contract = {
            "fact_id": "fixture",
            "domain": "social",
            "estimand": "fixture",
            "source_field": "pop_density_per_km2_polygon_area",
            "implementation_method": "median_difference",
        }
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.npz"
            sample = sample_for_estimand(data, contract, scale_km=500)
            cluster_bootstrap(
                sample,
                contract,
                scale_km=500,
                target_valid=10,
                task_key="same-key",
                checkpoint=checkpoint,
                resume=True,
            )
            with np.load(checkpoint, allow_pickle=False) as payload:
                first_metadata = json.loads(str(payload["metadata_json"].item()))
            changed = sample.copy()
            changed.loc[0, "pop_density_per_km2_polygon_area"] = 40.0
            cluster_bootstrap(
                changed,
                contract,
                scale_km=500,
                target_valid=10,
                task_key="same-key",
                checkpoint=checkpoint,
                resume=True,
            )
            with np.load(checkpoint, allow_pickle=False) as payload:
                second_metadata = json.loads(str(payload["metadata_json"].item()))
            self.assertEqual(second_metadata["task_key"], "same-key")
            self.assertNotEqual(first_metadata["sample_sha256"], second_metadata["sample_sha256"])

    def test_analysis_configuration(self) -> None:
        config = yaml.safe_load((REPO_ROOT / "config/analysis.yml").read_text(encoding="utf-8"))
        self.assertEqual(config["expected"]["robust"], 16)
        self.assertEqual(config["expected"]["sensitive"], 2)
        self.assertEqual(config["expected"]["not_supported"], 3)
        self.assertEqual(config["et0"]["status"], "approved_and_retained_raw_unit_caution")

    def test_small_full_inference_orchestration_resumes(self) -> None:
        rows = []
        for block in range(4):
            for label, value in (("BWh oases", 10.0 + block), ("BWk oases", 2.0 + block)):
                rows.append(
                    {
                        "OasisID": f"{block}-{label}",
                        "class_label_en": label,
                        "pop_density_per_km2_polygon_area": value,
                        "ghsl_qc": "pass",
                        "area_km2": 1.0,
                        "block_250km": f"EE8857_250km_{block * 4}_0",
                        "block_500km": f"EE8857_500km_{block * 2}_0",
                        "block_1000km": f"EE8857_1000km_{block}_0",
                    }
                )
        data = pd.DataFrame(rows)
        contract = pd.DataFrame(
            [
                {
                    "fact_id": "fixture-01",
                    "domain": "social",
                    "estimand": "fixture_median_difference",
                    "source_field": "pop_density_per_km2_polygon_area",
                    "implementation_method": "median_difference",
                    "support_class": "robust",
                }
            ]
        )
        parameters = {
            "primary_replicates": 20,
            "primary_extension_replicates": 50,
            "sensitivity_replicates": 10,
            "sensitivity_extension_replicates": 20,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            first = run_full_inference(data, contract, output, **parameters)
            second = run_full_inference(data, contract, output, resume=True, **parameters)
            log = (output / "inference.log").read_text(encoding="utf-8")
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(second["status"], "PASS")
        self.assertIn("task resumed", log)


if __name__ == "__main__":
    unittest.main()
