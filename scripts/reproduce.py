#!/usr/bin/env python3
"""Verify this release and write a machine-readable reproduction receipt.

Usage
-----
    python scripts/reproduce.py                 # verify the release
    python scripts/reproduce.py --resume        # continue an interrupted run
    python scripts/reproduce.py --strict-ne     # treat every NE record as a failure
    python scripts/reproduce.py --write-sums    # (re)pin SHA256SUMS.txt
    python scripts/reproduce.py --full-bootstrap  # also re-draw the cluster bootstrap

What the default path does and does not do
------------------------------------------
It recomputes all 31 *point* estimands from ``data/analysis_input_minimal.csv``
and compares them to ``data/primary_estimands_31.csv`` row by row, including
the per-estimand sample sizes. It does **not** re-draw the cluster bootstrap:
the 95% intervals and FDR q-values are checked for internal consistency
against the locked ledger, not independently re-derived. That is stated on the
console, not only in the JSON receipt, because it is the boundary a reviewer
most needs to know. Pass ``--full-bootstrap`` to re-derive them.

Outputs land in ``<repo>/../reproduction_output`` by default, outside the
repository, so verifying never dirties the working tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The implementation lives in code/core/. `from code.core...` is impossible:
# the standard library ships a module named `code`, which shadows the
# directory. Putting `code/` on sys.path and importing `core.<module>` is the
# only import route that works, and it is the one the validator documents.
sys.path.insert(0, str(REPO_ROOT / "code"))

from core.validate_release import (  # noqa: E402
    EXPECTED_ESTIMANDS,
    ValidationFailure,
    validate_repository,
    write_checksums,
)


def _default_output_dir() -> Path:
    return REPO_ROOT.parent / "reproduction_output"


def _print_not_estimable(records: list[dict[str, object]]) -> None:
    print()
    print(f"NOT ESTIMABLE ({len(records)} record(s)) -- reported, not silently dropped:")
    for record in records:
        affected = record.get("affected") or []
        shown = ", ".join(str(item) for item in affected[:6])
        if len(affected) > 6:
            shown += f", ... (+{len(affected) - 6} more)"
        print(f"  [{record['code']}] {record['subject']}")
        print(f"      work package : {record.get('work_package')}")
        print(f"      reason       : {record['reason']}")
        print(
            f"      affected     : {record.get('affected_count')} "
            f"of {record.get('denominator')}"
            + (f" -> {shown}" if shown else "")
        )
        print(f"      impact       : {record['impact']}")
        print(f"      remedy       : {record['remedy']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the 3,437-oasis / "
            f"{EXPECTED_ESTIMANDS}-estimand release and emit a reproduction receipt."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write the receipt (default: <repo>/../reproduction_output).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue an interrupted run instead of starting over.",
    )
    parser.add_argument(
        "--strict-ne",
        action="store_true",
        help=(
            "Fail if any check reports a not-estimable record. Use this once the "
            "gaps those records name have been closed."
        ),
    )
    parser.add_argument(
        "--write-sums",
        action="store_true",
        help=(
            "Write SHA256SUMS.txt for the seven required inputs and exit. Run this "
            "LAST, after every shipped file is final."
        ),
    )
    parser.add_argument(
        "--full-bootstrap",
        action="store_true",
        help=(
            f"Additionally re-draw the cluster bootstrap for all {EXPECTED_ESTIMANDS} "
            "estimands, re-deriving the 95% intervals and FDR q-values instead of "
            "verifying the locked ledger. Slow; opt-in by design."
        ),
    )
    args = parser.parse_args(argv)

    if args.write_sums:
        target = write_checksums(REPO_ROOT)
        print(f"WROTE: {target.relative_to(REPO_ROOT).as_posix()}")
        print(target.read_text(encoding="utf-8").rstrip("\n"))
        return 0

    output_dir = args.output_dir or _default_output_dir()
    try:
        qa = validate_repository(
            REPO_ROOT, output_dir, resume=args.resume, strict_ne=args.strict_ne
        )
    except ValidationFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    summary = qa["summary"]
    status = qa["status"]
    print(
        f"{status}: {summary['estimands_recomputed']}/{summary['estimands']} estimands "
        f"recomputed and matched; "
        f"{summary['robust']} robust, {summary['sensitive']} sensitive, "
        f"{summary['not_supported']} not_supported"
    )
    print(
        f"       population {summary['analysis_population']} oases "
        f"({summary['historical_universe']} historical universe minus "
        f"{summary['excluded_identifiers']} excluded identifiers); "
        f"baseline {qa['analysis_baseline']}"
    )
    print(f"       BOUNDARY: {summary['reproduction_boundary']}.")
    if not args.full_bootstrap:
        print(
            "       Bootstrap NOT recomputed on this path. "
            "Use --full-bootstrap to re-derive intervals and q-values."
        )

    records = qa.get("not_estimable") or []
    if records:
        _print_not_estimable(records)

    print()
    print(f"Receipt: {(output_dir / 'reproduction_QA.json').resolve()}")
    print(f"State:   {(output_dir / 'reproduction_state.json').resolve()}")
    print(f"Log:     {(output_dir / 'reproduction.log').resolve()}")

    if args.full_bootstrap:
        import pandas as pd

        from core.inference import run_full_inference

        print()
        print(
            f"Re-drawing the cluster bootstrap for all {EXPECTED_ESTIMANDS} estimands. "
            "This replaces trust in the locked ledger with a fresh derivation and "
            "takes considerably longer than the default path."
        )
        data = pd.read_csv(REPO_ROOT / "data/analysis_input_minimal.csv", low_memory=False)
        contract = pd.read_csv(REPO_ROOT / "config/estimands_31.csv")
        locked = pd.read_csv(REPO_ROOT / "data/primary_estimands_31.csv")
        inference = run_full_inference(
            data,
            contract,
            output_dir / "full_inference",
            locked_primary=locked,
            resume=args.resume,
        )
        print(json.dumps(inference.get("summary", inference), indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
