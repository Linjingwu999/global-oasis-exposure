from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.validate_release import ValidationFailure, validate_repository
from src.inference import run_full_inference


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute point estimands and verify all locked release outputs."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT.parent / f"{REPO_ROOT.name}-reproduction-output",
        help="Output directory; defaults to a sibling outside the repository.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse a prior PASS result only when every required input hash is unchanged.",
    )
    parser.add_argument(
        "--full-bootstrap",
        action="store_true",
        help="Opt in to the full 21-estimand bootstrap/FDR/sensitivity orchestration; this is not run by the default locked-integrity check.",
    )
    args = parser.parse_args()
    try:
        qa = validate_repository(REPO_ROOT, args.output_dir, resume=args.resume)
    except (ValidationFailure, KeyError, ValueError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    suffix = " (resumed)" if qa.get("resumed") else ""
    print(
        "PASS: 21/21 estimands; 16 robust, 2 sensitive, "
        f"3 not_supported; 29/29 facts{suffix}"
    )
    if args.full_bootstrap:
        data = pd.read_csv(REPO_ROOT / "data/analysis_input_minimal.csv", low_memory=False)
        contract = pd.read_csv(REPO_ROOT / "config/estimands.csv")
        locked = pd.read_csv(REPO_ROOT / "data/primary_estimands_21.csv")
        full = run_full_inference(
            data,
            contract,
            args.output_dir / "full_inference",
            locked_primary=locked,
            resume=args.resume,
        )
        if full["status"] != "PASS":
            print(f"FAIL: full bootstrap orchestration: {full}", file=sys.stderr)
            return 1
        print("PASS: full 500-km bootstrap, domain BH FDR, and 250/1,000-km sensitivities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
