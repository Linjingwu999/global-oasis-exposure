"""Release-integrity verification for the 3,437-oasis / 31-estimand analysis.

This module is the ported successor of the v1.0.0 validator. It verifies the
*current* release: 3,437 analysis oases and 31 primary estimands. Every
constant below was recomputed from the shipped authoritative files, not copied
from v1.0.0.

Two v1.0.0 work packages no longer exist and were deleted rather than adapted:

* ``_workbook_qa`` -- one of its two comparison targets,
  ``data/master_numeric_facts_29.csv``, no longer exists. Its genuinely useful
  part, the privacy regex scan, was re-homed onto the shipped text files as
  :func:`_privacy_qa`. The other target, ``data/Source_Data_CEE_v1.xlsx``, was
  rebuilt for this population and does ship; it is covered by
  :data:`RELEASE_SURFACE_GLOBS` and the checksum manifest, but its cell
  contents are not re-derived here.
* the ``master_numeric_facts_29.csv`` fact ledger -- the four *inferential*
  FuturePop comparisons were promoted into the 31-row estimand table as
  first-class rows (``F04-PRIMARY-22`` .. ``F04-PRIMARY-25``), each carrying a
  CI and an FDR q-value. The descriptive ``F04-FUTUREPOP-*`` and
  ``F04-CONTEXT-*`` facts were not promoted and were not retired: they keep
  their v1.0.0 identifiers and meanings in the Source Data workbook.

Reporting policy
----------------
A check that cannot be evaluated is never silently skipped and never relaxed
into a weaker check that happens to pass. It is recorded as an explicit
not-estimable (NE) record naming the subject, the reason, the affected items,
the denominator and the consequence. NE records are surfaced in
``reproduction_QA.json`` under ``not_estimable`` and printed by
``scripts/reproduce.py``. Pass ``strict_ne=True`` to promote every NE record
into a hard failure once the underlying gaps are closed.

Reproduction boundary
---------------------
The default path recomputes all 31 *point* estimands from
``data/analysis_input_minimal.csv`` and compares them row by row against the
locked ledger. It does **not** re-draw the cluster bootstrap: ``ci95_low``,
``ci95_high`` and ``fdr_q`` are verified for internal consistency against the
shipped ledger, not independently re-derived. Use
``scripts/reproduce.py --full-bootstrap`` for that.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .estimands import (
    compute_point_estimands,
    point_result,
    q_pass,
    qa_field_for,
    sample_for_estimand,
)
from .io_utils import atomic_bytes, atomic_csv, atomic_json, sha256
from .sensitivity import futurepop_accounting, validate_locked_sensitivity
from .spatial_blocks import validate_block_mapping


# --------------------------------------------------------------------------
# Required release inputs
# --------------------------------------------------------------------------
# Seven files, down from v1.0.0's eight. Dropped: ``numeric_facts``
# (master_numeric_facts_29.csv, deleted) and ``source_data``
# (Source_Data_CEE_v1.xlsx, which ships but is a *product* of these inputs
# rather than one of them, so requiring it here would be circular). Added:
# ``product_manifest_current``, which is a *different schema* from
# ``third_party_boundary`` -- only the latter carries
# ``raw_files_redistributed``.
REQUIRED_FILES = {
    "analysis_config": "config/analysis.yml",
    "estimand_contract": "config/estimands_31.csv",
    "minimum_input": "data/analysis_input_minimal.csv",
    "primary_estimands": "data/primary_estimands_31.csv",
    "data_dictionary": "data/data_dictionary.csv",
    "third_party_boundary": "data/third_party_product_boundary.csv",
    "product_manifest_current": "data/source_product_manifest_current.csv",
}

CHECKSUM_FILE = "SHA256SUMS.txt"

# The six identifiers removed from the 3,443-oasis historical universe to form
# the 3,437-oasis analysis population. They must not appear in any release
# artefact except the files that *declare* the exclusion.
EXCLUDED_IDS = (
    "ASTJ10032",
    "ASTR04013",
    "ASTR08004",
    "ASTR08020",
    "ASTR08029",
    "ASTR08036",
)
HISTORICAL_UNIVERSE = 3443
ANALYSIS_POPULATION = 3437

# Files permitted to name the excluded identifiers, because declaring the
# exclusion list is their job. Everywhere else, naming one is a leak.
EXCLUSION_DECLARING_FILES = frozenset(
    {
        "code/core/validate_release.py",
        "tests/verify_current_minimum.py",
        "tests/test_locked_outputs.py",
    }
)

# Files permitted to name the retired v1.0.0 artefacts, for the same reason:
# a guard against an artefact returning has to be able to say what it is
# guarding against. The alternative -- obfuscating the names in the guard's own
# documentation -- would trade a real explanation for a passing scan.
RETIREMENT_DECLARING_FILES = frozenset(
    {
        "code/core/validate_release.py",
        "tests/verify_current_minimum.py",
        "tests/test_locked_outputs.py",
    }
)

# --------------------------------------------------------------------------
# Locked composition of the analysis population
# --------------------------------------------------------------------------
# Only ``non-BW oases`` moved relative to v1.0.0 (748 -> 742): all six excluded
# identifiers were non-BW. The strict BWh/BWk counts are unchanged, which is
# why every point estimate still reproduces.
EXPECTED_CLASS_COUNTS = {
    "BWh oases": 1822,
    "BWk oases": 742,
    "non-BW oases": 742,
    "BWh/BWk oases": 131,
}
# Asia moved 1593 -> 1587: all six exclusions are Asian.
EXPECTED_CONTINENT_COUNTS = {
    "Asia": 1587,
    "Africa": 1096,
    "North America": 591,
    "South America": 123,
    "Oceania": 40,
}
EXPECTED_DATA_SHAPE = (3437, 219)

# Occupied spatial blocks. The strict BWh/BWk counts are the bootstrap's
# cluster counts and are unchanged from v1.0.0; the all-rows counts moved with
# the six exclusions.
EXPECTED_STRICT_BLOCK_COUNTS = {"250": 352, "500": 148, "1000": 65}
EXPECTED_ALL_BLOCK_COUNTS = {"250": 394, "500": 155, "1000": 65}

# BH multiple-testing family sizes. This is the single most consequential
# constant in the file: it is the BH denominator, so changing it silently
# changes every ``fdr_q``. ``water`` grew 3 -> 5 because ET0
# (F04-PRIMARY-30) and ET0-SD (F04-PRIMARY-31) are now inside the contract.
EXPECTED_DOMAIN_FAMILY_SIZES = {
    "social": 2,
    "water": 5,
    "utci": 4,
    "nex": 12,
    "futurepop": 4,
    "economic_nightlights": 4,
}
EXPECTED_SUPPORT_COUNTS = {"robust": 23, "not_supported": 6, "sensitive": 2}
EXPECTED_FACT_IDS = [f"F04-PRIMARY-{index:02d}" for index in range(1, 32)]
EXPECTED_ESTIMANDS = 31
EXPECTED_BASELINE_ID = "analysis_release_3437"

# QC pass counts. ``futurepop_qc`` is listed deliberately and is deliberately
# NOT used as an inclusion gate anywhere: it passes only 545 of 3,437 rows
# (``pass_coverage_ge099_all``) because it is a *coverage diagnostic*. Routing
# it through the sampling gate reproduces a rejected sensitivity variant
# (n = 362/71) instead of the published FuturePop effects, which is why
# ``estimands.qa_field_for`` returns ``None`` for every ``pop_ssp*`` field.
EXPECTED_QC_PASS = {
    "country_qc": 3436,
    "hydrobasins_qc": 3427,
    "kg_qc": 3437,
    "ghsl_qc": 3437,
    "jrc_qc": 3437,
    "terraclimate_qc": 3437,
    "ai_qc": 3437,
    "et0_qc": 3437,
    "utci_qc": 3437,
    "nex_qc": 3437,
    "futurepop_qc": 545,
    "gdp_qc": 3437,
    "viirs_qc": 3437,
    "aridity_ai_qc": 3437,
}
EXPECTED_NEX_METHODS = {"polygon_reducer": 2865, "representative_point_fallback": 572}
EXPECTED_FUTUREPOP = {"coverage_gt0": 3181, "coverage_ge050": 2248, "no_valid": 256}

# Observed maximum of ``ai_scaled`` is 0.5210675904639034. v1.0.0 allowed
# [0, 10], which is so loose it would not catch an unscaled column; tightened.
AI_PLAUSIBLE_RANGE = (0.0, 2.0)
EXPECTED_AI_VALID = 3437
EXPECTED_AI_SCALE_FACTOR = 0.0001

ET0_FIELDS = (
    "et0_qc",
    "et0_v31_yr_raw_valid_pixel_count",
    "et0_v31_yr_raw_area_weighted_mean_raw",
    "et0_v31_yr_sd_raw_valid_pixel_count",
    "et0_v31_yr_sd_raw_area_weighted_mean_raw",
)
# ET0 is now INSIDE the contract. v1.0.0 asserted the opposite; the assertion
# is inverted rather than deleted so a silent removal is still caught.
EXPECTED_ET0_ESTIMANDS = {
    "F04-PRIMARY-30": "et0_v31_yr_raw_area_weighted_mean_raw",
    "F04-PRIMARY-31": "et0_v31_yr_sd_raw_area_weighted_mean_raw",
}

FUTUREPOP_FIELDS = ("pop_ssp2_2050", "pop_ssp2_2080", "pop_ssp5_2050", "pop_ssp5_2080")

# --------------------------------------------------------------------------
# Release surface and hygiene
# --------------------------------------------------------------------------
RELEASE_SURFACE_GLOBS = (
    "README.md",
    "CITATION.cff",
    "LICENSE",
    "LICENSE-DATA",
    "THIRD_PARTY_NOTICES.md",
    "environment.yml",
    ".gitignore",
    "SHA256SUMS.txt",
    "config/*.yml",
    "config/*.csv",
    "data/*.csv",
    "data/*.xlsx",
    "code/core/*.py",
    "tests/*.py",
    "scripts/*.py",
    "docs/*.md",
)
HYGIENE_SKIP_DIRS = frozenset(
    {".git", "__pycache__", "reproduction_output", ".pytest_cache", ".venv", "env"}
)
# Build by-products and editor droppings never belong in a published manifest.
CHECKSUM_SKIP_SUFFIXES = frozenset({".pyc", ".pyo", ".tmp", ".bak", ".swp", ".log"})
TEXT_SUFFIXES = frozenset({".py", ".csv", ".yml", ".yaml", ".md", ".txt", ".cff", ".json"})
EXTENSIONLESS_TEXT_FILES = frozenset({"LICENSE", "LICENSE-DATA", ".gitignore"})

PRIVACY_PATTERNS = {
    "windows_absolute_path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\"),
    "posix_home_path": re.compile(r"/(?:Users|home)/[^/\s]+/"),
    "sandbox_path": re.compile(r"sandbox" + r":/|/mnt" + r"/data/"),
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
}

# Retired v1.0.0 artefact and layout names. This is a ratchet: it must stay at
# zero hits inside the declared release surface.
#
# NOTE: the bare number 3443 is deliberately NOT a retired token. It appears
# legitimately in ``data/third_party_product_boundary.csv`` ("3437 analytical
# polygons from 3443 historical universe"), which is exactly the provenance
# statement this release should carry, and as a substring of the ordinary
# float 3443.365043 in the analysis table. Banning it would punish correct
# provenance. The population is guarded positively instead, by asserting
# len(data) == 3437 and that the six excluded identifiers are absent.
#
# NOTE: ``Source_Data_CEE``, ``F04-FUTUREPOP-`` and ``F04-CONTEXT-`` were each
# listed here at one point and each was wrong. The Source Data workbook is not
# a retired artefact: it was rebuilt for the 3,437-oasis / 31-estimand
# population and ships in this release. The FUTUREPOP and CONTEXT identifiers
# are not a retired namespace either. What moved into the estimand table as
# ``F04-PRIMARY-22`` .. ``F04-PRIMARY-25`` were the four *inferential* FuturePop
# comparisons. The descriptive companions kept their own identifiers and their
# v1.0.0 meanings: ``F04-FUTUREPOP-01`` .. ``-04`` are coverage-aware
# descriptive class totals for the four ``pop_ssp*`` fields, ``-05`` is the
# coverage denominator, and ``F04-CONTEXT-01`` .. ``-03`` are the structural
# inventory counts. Banning them would have forced a rename that broke
# continuity with the published v1.0.0 fact identifiers for quantities that
# never changed meaning.
RETIRED_TOKENS = (
    "estimands_21",
    "primary_estimands_21",
    "master_numeric_facts",
    "NumericFacts29",
)
# ``source_product_manifest.csv`` was renamed; the current file is
# ``source_product_manifest_current.csv``, so the retired form must be matched
# without also matching its successor.
RETIRED_TOKEN_PATTERNS = {
    "source_product_manifest.csv (retired name)": re.compile(
        r"source_product_manifest\.csv"
    ),
    "src/ package layout (retired; now code/core/)": re.compile(r"(?<![\w.-])src/"),
}

SPECIAL_CHARACTERS = {
    "degree_sign": "°",
    "superscript_minus_one": "⁻¹",
    "minus_sign": "−",
    "multiplication_sign": "×",
}


class ValidationFailure(RuntimeError):
    """A release-integrity failure, as distinct from an unexpected crash."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationFailure(message)


def _close(actual: object, expected: object) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return bool(
        np.isclose(
            float(actual),
            float(expected),
            rtol=1e-10,
            atol=1e-10,
            equal_nan=True,
        )
    )


def _ne(
    code: str,
    subject: str,
    reason: str,
    *,
    affected: list[str] | None = None,
    affected_count: int | None = None,
    denominator: int | None = None,
    impact: str,
    remedy: str,
) -> dict[str, object]:
    """Build one explicit not-estimable record.

    A check that cannot be evaluated produces one of these instead of being
    dropped, zeroed, imputed or quietly weakened.
    """
    items = list(affected or [])
    return {
        "code": code,
        "subject": subject,
        "reason": reason,
        "affected": items,
        "affected_count": affected_count if affected_count is not None else len(items),
        "denominator": denominator,
        "impact": impact,
        "remedy": remedy,
    }


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------
def _release_surface(repo_root: Path) -> list[Path]:
    """Every file this release declares as shipped, deduplicated and sorted."""
    found: set[Path] = set()
    for pattern in RELEASE_SURFACE_GLOBS:
        if any(character in pattern for character in "*?["):
            found.update(path for path in repo_root.glob(pattern) if path.is_file())
        else:
            candidate = repo_root / pattern
            if candidate.is_file():
                found.add(candidate)
    return sorted(found)


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in EXTENSIONLESS_TEXT_FILES


def _walk_repository_text_files(repo_root: Path) -> list[Path]:
    return sorted(
        path
        for path in repo_root.rglob("*")
        if path.is_file()
        and not any(part in HYGIENE_SKIP_DIRS for part in path.relative_to(repo_root).parts)
        and _is_text_file(path)
    )


def _append_log(path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_bytes(path, f"{existing}{timestamp} {message}\n".encode("utf-8"))


# --------------------------------------------------------------------------
# Integrity: SHA-256 baseline
# --------------------------------------------------------------------------
def _published_files(repo_root: Path) -> list[Path]:
    """Every file this repository publishes, in manifest order."""
    found = [
        path
        for path in repo_root.rglob("*")
        if path.is_file()
        and not any(
            part in HYGIENE_SKIP_DIRS for part in path.relative_to(repo_root).parts
        )
        # The manifest cannot list itself.
        and path.name != CHECKSUM_FILE
        and path.suffix.lower() not in CHECKSUM_SKIP_SUFFIXES
    ]
    return sorted(found, key=lambda path: path.relative_to(repo_root).as_posix())


def write_checksums(repo_root: Path) -> Path:
    """Emit ``SHA256SUMS.txt`` for every published file.

    Uppercase hex, two-space separator, repo-relative POSIX path, LF endings,
    UTF-8 without BOM -- the ``sha256sum -c`` format, so a reviewer can verify
    the release without running Python.

    The manifest covers the whole published tree, not only the seven inputs
    :func:`_integrity_qa` verifies. Those seven are what this validator needs in
    order to re-derive results; a reader who downloads a DOI-minted archive
    wants to know that the *code* and the *documentation* are also the bytes
    that were archived. :func:`_integrity_qa` requires the manifest to cover the
    seven and ignores whatever else it carries, so the wider manifest satisfies
    it as a superset. Emitting only the seven, then having a second tool emit
    the full set to the same path, is how two mutually incompatible manifests
    end up fighting over one filename.

    Pin this LAST, after every shipped file is final: the digests are of the
    exact bytes on disk at the moment of writing.
    """
    repo_root = repo_root.resolve()
    published = _published_files(repo_root)
    covered = {path.relative_to(repo_root).as_posix() for path in published}
    uncovered = sorted(set(REQUIRED_FILES.values()) - covered)
    _require(not uncovered, f"Cannot checksum missing required files: {uncovered}")
    lines = [
        f"{sha256(path)}  {path.relative_to(repo_root).as_posix()}" for path in published
    ]
    target = repo_root / CHECKSUM_FILE
    atomic_bytes(target, ("\n".join(lines) + "\n").encode("utf-8"))
    return target


def _read_checksums(path: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        _require(len(parts) == 2, f"Malformed {CHECKSUM_FILE} line {number}: {line!r}")
        digests[parts[1].strip().lstrip("*")] = parts[0].strip().upper()
    return digests


def _integrity_qa(
    repo_root: Path, input_hashes: dict[str, str]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Verify the shipped digests against ``SHA256SUMS.txt`` when it exists.

    v1.0.0 pinned eight digests as Python literals. All eight described the
    3,443-oasis / 21-estimand release and none of them were carried over: a
    literal baked into the validator goes stale the moment any shipped file is
    regenerated, and a stale literal is indistinguishable from a real
    corruption. The baseline lives in a data file instead.
    """
    observed = {
        relative: input_hashes[name] for name, relative in REQUIRED_FILES.items()
    }
    checksum_path = repo_root / CHECKSUM_FILE
    if not checksum_path.is_file():
        return (
            {
                "status": "NOT_PINNED",
                "checksum_file": CHECKSUM_FILE,
                "observed_sha256": observed,
            },
            [
                _ne(
                    "NE-INTEGRITY-BASELINE",
                    f"{CHECKSUM_FILE} is absent",
                    "No pinned SHA-256 baseline ships with this release, so a silently "
                    "edited input cannot be detected by digest comparison.",
                    affected=sorted(observed),
                    denominator=len(observed),
                    impact="File-level tamper detection is unavailable. Every other "
                    "check in this validator still runs against the file contents, "
                    "so corruption that changes a value is still caught; corruption "
                    "that does not change any checked value is not.",
                    remedy="After every shipped file is final, run "
                    "`python scripts/reproduce.py --write-sums` and commit "
                    f"{CHECKSUM_FILE}.",
                )
            ],
        )

    expected = _read_checksums(checksum_path)
    missing = sorted(set(observed) - set(expected))
    _require(not missing, f"{CHECKSUM_FILE} does not cover: {missing}")
    mismatches = {
        relative: {"expected": expected[relative], "actual": digest}
        for relative, digest in observed.items()
        if expected[relative] != digest
    }
    _require(
        not mismatches,
        f"Authoritative release hash mismatch against {CHECKSUM_FILE}: {mismatches}. "
        "Either a shipped input was modified without authorisation, or the file was "
        "regenerated on purpose and the baseline was not re-pinned. Every content "
        "check in this validator runs independently of these digests, so if the rest "
        "of this run passes, a stale baseline is the likelier explanation -- confirm "
        "the change was intended, then re-pin with "
        "`python scripts/reproduce.py --write-sums`.",
    )
    return (
        {
            "status": "PASS",
            "checksum_file": CHECKSUM_FILE,
            "verified_files": len(observed),
            "observed_sha256": observed,
        },
        [],
    )


# --------------------------------------------------------------------------
# Resume machinery
# --------------------------------------------------------------------------
def _load_interrupted_state(
    path: Path, fingerprint: dict[str, str], resume: bool
) -> dict[str, Any] | None:
    if not resume or not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if state.get("resume_fingerprint_sha256") != fingerprint:
        return None
    return state


def _resume_result(output_dir: Path, fingerprint: dict[str, str]) -> dict[str, Any] | None:
    state_path = output_dir / "reproduction_state.json"
    qa_path = output_dir / "reproduction_QA.json"
    if not state_path.exists() or not qa_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if state.get("status") in ("PASS", "PASS_WITH_NE") and state.get(
        "resume_fingerprint_sha256"
    ) == fingerprint:
        qa["resumed"] = True
        return qa
    return None


def _resumable_point_estimands(
    data: pd.DataFrame,
    contract: pd.DataFrame,
    output_dir: Path,
    state: dict[str, Any],
    log_path: Path,
    *,
    resume: bool,
) -> tuple[pd.DataFrame, list[dict[str, str]], int]:
    """Recompute every point estimand, checkpointing after each one.

    This deliberately drives ``sample_for_estimand`` / ``point_result`` row by
    row rather than calling ``compute_point_estimands``, so that a crash
    resumes mid-run and so that a failing estimand is individually
    attributable while unrelated estimands still run.

    Do NOT "simplify" this into ``compute_point_estimands(strict=False)``:
    ``strict=False`` is precisely the mode that let ten estimands fail
    unnoticed. The per-row failure ledger below is the point.
    """
    state_path = output_dir / "reproduction_state.json"
    work = state["work_packages"]["point_estimands"]
    work["status"] = "running"
    state["status"] = "running"
    atomic_json(state_path, state)
    _append_log(log_path, "point_estimands running")
    result_dir = output_dir / "estimand_results"
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    resumed_count = 0
    for row in contract.to_dict("records"):
        fact_id = str(row["fact_id"])
        estimand = str(row["estimand"])
        result_path = result_dir / f"{fact_id}.json"
        item = work["items"].setdefault(fact_id, {"status": "pending", "estimand": estimand})
        can_resume = (
            resume
            and item.get("status") == "success"
            and result_path.is_file()
            and item.get("result_sha256") == sha256(result_path)
        )
        if can_resume:
            try:
                stored = json.loads(result_path.read_text(encoding="utf-8"))
                if stored.get("estimand") != estimand:
                    raise ValueError("stored estimand identity changed")
                results.append(stored)
                resumed_count += 1
                _append_log(log_path, f"point_estimand resumed {fact_id}")
                continue
            except (OSError, ValueError, json.JSONDecodeError):
                can_resume = False
        item.update({"status": "running", "estimand": estimand})
        atomic_json(state_path, state)
        _append_log(log_path, f"point_estimand running {fact_id}")
        try:
            sample = sample_for_estimand(data, row)
            result = point_result(sample, row)
            atomic_json(result_path, result)
            item.update(
                {"status": "success", "result_sha256": sha256(result_path), "error": None}
            )
            results.append(result)
            atomic_csv(
                output_dir / "regenerated_point_estimands_partial.csv",
                pd.DataFrame(results),
            )
            _append_log(log_path, f"point_estimand success {fact_id}")
        except Exception as exc:
            item.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            failures.append({"estimand": estimand, "fact_id": fact_id, "error": str(exc)})
            _append_log(log_path, f"point_estimand failed {fact_id} {type(exc).__name__}: {exc}")
        atomic_json(state_path, state)
    if failures:
        work["status"] = "failed"
        state["status"] = "failed"
        atomic_json(state_path, state)
        _append_log(log_path, f"point_estimands failed count={len(failures)}")
    else:
        work["status"] = "success"
        atomic_json(state_path, state)
        _append_log(
            log_path, f"point_estimands success count={len(results)} resumed={resumed_count}"
        )
    return pd.DataFrame(results), failures, resumed_count


# --------------------------------------------------------------------------
# Work package: recomputed point estimates vs the locked ledger
# --------------------------------------------------------------------------
def _point_estimate_qa(
    regenerated: pd.DataFrame,
    failures: list[dict[str, str]],
    primary: pd.DataFrame,
    resumed_count: int,
) -> dict[str, object]:
    _require(not failures, f"Point-estimation failures: {failures}")
    _require(
        len(regenerated) == EXPECTED_ESTIMANDS,
        f"Regenerated estimands={len(regenerated)}, expected {EXPECTED_ESTIMANDS}",
    )
    locked = primary.set_index("fact_id", drop=False)
    mismatches: list[dict[str, object]] = []
    compared_fields = ("estimate_bwh", "estimate_bwk", "effect_bwh_minus_bwk")
    worst_delta: dict[str, float] = {field: 0.0 for field in compared_fields}
    for row in regenerated.to_dict("records"):
        fact_id = str(row["fact_id"])
        if fact_id not in locked.index:
            mismatches.append({"fact_id": fact_id, "field": "missing_locked_row"})
            continue
        expected = locked.loc[fact_id]
        if str(row["estimand"]) != str(expected["estimand"]):
            mismatches.append(
                {
                    "fact_id": fact_id,
                    "field": "estimand",
                    "actual": row["estimand"],
                    "expected": expected["estimand"],
                }
            )
        # The n-counts are the check that catches a QC-gate regression, e.g.
        # wrongly gating pop_ssp* on futurepop_qc, which would collapse
        # n_bwh/n_bwk to roughly 362/71 while leaving the arithmetic "valid".
        for field in ("n_bwh", "n_bwk"):
            if int(row[field]) != int(float(expected[field])):
                mismatches.append(
                    {
                        "fact_id": fact_id,
                        "field": field,
                        "actual": row[field],
                        "expected": expected[field],
                    }
                )
        for field in compared_fields:
            delta = abs(float(row[field]) - float(expected[field]))
            worst_delta[field] = max(worst_delta[field], delta)
            if not _close(row[field], expected[field]):
                mismatches.append(
                    {
                        "fact_id": fact_id,
                        "field": field,
                        "actual": row[field],
                        "expected": expected[field],
                        "abs_delta": delta,
                    }
                )
    _require(not mismatches, f"Locked point-estimate mismatches: {mismatches[:5]}")

    strict_n = {
        "n_bwh": sorted({int(row["n_bwh"]) for row in regenerated.to_dict("records")}),
        "n_bwk": sorted({int(row["n_bwk"]) for row in regenerated.to_dict("records")}),
    }
    _require(
        strict_n == {"n_bwh": [1822], "n_bwk": [742]},
        f"Strict-sample sizes are no longer uniform across estimands: {strict_n}",
    )

    not_estimable: list[dict[str, object]] = []
    ratio_rows = regenerated.loc[
        regenerated["effect_ratio_bwh_over_bwk"].notna(), "fact_id"
    ].astype(str).tolist()
    if "effect_ratio_bwh_over_bwk" not in primary.columns:
        not_estimable.append(
            _ne(
                "NE-RATIO-COLUMN",
                "effect_ratio_bwh_over_bwk cannot be cross-checked",
                "The recomputation produces a back-transformed BWh/BWk ratio for the "
                "median_log_ratio estimands, but data/primary_estimands_31.csv ships "
                "no effect_ratio_bwh_over_bwk column to compare it against.",
                affected=ratio_rows,
                denominator=EXPECTED_ESTIMANDS,
                impact="The ratio is verified only indirectly, through the log-scale "
                "effect_bwh_minus_bwk, which does match exactly. No ratio is "
                "reported as verified when it is not.",
                remedy="Add effect_ratio_bwh_over_bwk to data/primary_estimands_31.csv "
                "for the median_log_ratio estimands, then this becomes an exact check.",
            )
        )

    return {
        "status": "PASS",
        "regenerated": len(regenerated),
        "failures": failures,
        "mismatches": mismatches,
        "resumed_estimators": resumed_count,
        "unrelated_estimators_continue_after_failure": True,
        "strict_sample_sizes": strict_n,
        "worst_absolute_deviation": worst_delta,
        "comparison_tolerance": {"rtol": 1e-10, "atol": 1e-10},
        "ratio_bearing_estimands": ratio_rows,
        "bootstrap_recomputed": False,
        "bootstrap_mode": "locked_outputs_verified",
        "not_estimable": not_estimable,
    }


# --------------------------------------------------------------------------
# Work package: internal consistency of the shipped ledger
# --------------------------------------------------------------------------
def _locked_output_qa(contract: pd.DataFrame, primary: pd.DataFrame) -> dict[str, object]:
    _require(
        len(contract) == EXPECTED_ESTIMANDS,
        f"Estimand contract has {len(contract)} rows, expected {EXPECTED_ESTIMANDS}",
    )
    _require(
        len(primary) == EXPECTED_ESTIMANDS,
        f"Primary table has {len(primary)} rows, expected {EXPECTED_ESTIMANDS}",
    )
    _require(primary["fact_id"].is_unique, "Primary fact IDs are not unique")
    _require(contract["fact_id"].is_unique, "Contract fact IDs are not unique")
    _require(
        contract["fact_id"].tolist() == EXPECTED_FACT_IDS,
        "Contract fact IDs or their order changed",
    )
    _require(
        primary["fact_id"].tolist() == EXPECTED_FACT_IDS,
        "Primary fact IDs or their order changed",
    )
    _require(
        primary["baseline_id"].astype(str).eq(EXPECTED_BASELINE_ID).all(),
        "Primary ledger baseline_id is not uniformly " + EXPECTED_BASELINE_ID,
    )

    contract_indexed = contract.set_index("fact_id", drop=False)
    primary_indexed = primary.set_index("fact_id", drop=False)

    # Descriptive columns must agree between the contract and the ledger.
    projection_columns = [
        "fact_id",
        "domain",
        "estimand",
        "statistic",
        "unit",
        "effect_scale",
        "support_class",
    ]
    populated = contract_indexed[projection_columns].notna().all(axis=1).to_numpy()
    incomplete_ids = contract_indexed.index[~populated].astype(str).tolist()
    incomplete_columns = sorted(
        column
        for column in contract.columns
        if bool(contract[column].isna().any())
    )
    populated_ids = contract_indexed.index[populated]
    left = (
        contract_indexed.loc[populated_ids, projection_columns]
        .astype("string")
        .reset_index(drop=True)
    )
    right = (
        primary_indexed.loc[populated_ids, projection_columns]
        .astype("string")
        .reset_index(drop=True)
    )
    _require(
        left.equals(right),
        "Contract and locked ledger disagree on the descriptive columns for the "
        "fully populated estimands",
    )

    not_estimable: list[dict[str, object]] = []
    if incomplete_ids:
        not_estimable.append(
            _ne(
                "NE-CONTRACT-INCOMPLETE",
                "contract-vs-ledger projection is verified on a subset only",
                "config/estimands_31.csv leaves "
                f"{len(incomplete_columns)} columns empty for {len(incomplete_ids)} "
                "estimands, so those rows carry no contract-side value to compare "
                "against the ledger. The ledger itself does carry the values.",
                affected=incomplete_ids,
                denominator=EXPECTED_ESTIMANDS,
                impact=(
                    f"The projection check covers {int(populated.sum())} of "
                    f"{EXPECTED_ESTIMANDS} estimands. For the remaining "
                    f"{len(incomplete_ids)}, a contract/ledger divergence in "
                    f"{incomplete_columns} would not be detected. Their fact_id, "
                    "domain, estimand, source_field and implementation_method ARE "
                    "populated and ARE checked, and their point estimates reproduce "
                    "exactly, so the analysis itself is unaffected."
                ),
                remedy="Populate " + ", ".join(incomplete_columns) + " for "
                + ", ".join(incomplete_ids)
                + " in config/estimands_31.csv from data/primary_estimands_31.csv, "
                "then rerun with strict_ne=True.",
            )
        )

    support = primary["support_class"].value_counts().to_dict()
    _require(
        support == EXPECTED_SUPPORT_COUNTS,
        f"Support classification changed: {support}",
    )
    families = contract.groupby("domain", sort=False).size().to_dict()
    _require(
        families == EXPECTED_DOMAIN_FAMILY_SIZES,
        f"BH family sizes changed: {families}",
    )
    _require(
        sum(families.values()) == EXPECTED_ESTIMANDS,
        f"BH family sizes do not sum to {EXPECTED_ESTIMANDS}: {families}",
    )

    ci_low = pd.to_numeric(primary["ci95_low"], errors="coerce")
    ci_high = pd.to_numeric(primary["ci95_high"], errors="coerce")
    effect = pd.to_numeric(primary["effect_bwh_minus_bwk"], errors="coerce")
    q_values = pd.to_numeric(primary["fdr_q"], errors="coerce")
    _require(
        bool((ci_low.notna() & ci_high.notna() & (ci_low <= ci_high)).all()),
        "Invalid confidence intervals",
    )
    _require(
        bool((ci_low <= effect).all() and (effect <= ci_high).all()),
        "A point estimate falls outside its own 95% interval: "
        + str(primary.loc[~((ci_low <= effect) & (effect <= ci_high)), "fact_id"].tolist()),
    )
    _require(
        bool((q_values.notna() & q_values.between(0, 1)).all()),
        "Invalid FDR q-values",
    )
    # A percentile bootstrap with 2,000 replicates cannot resolve a two-sided
    # p-value below 2/2001; no BH-adjusted q may sit under that floor.
    q_floor = 2.0 / 2001.0
    below_floor = primary.loc[q_values < q_floor - 1e-12, "fact_id"].tolist()
    _require(
        not below_floor,
        f"FDR q-values below the 2,000-replicate resolution floor {q_floor:.12g}: "
        f"{below_floor}",
    )

    # The BH rule itself cannot be replayed: the ledger ships no p-values.
    inference_columns = ("p_two_sided", "occupied_blocks", "bootstrap_valid_replicates")
    absent = [name for name in inference_columns if name not in primary.columns]
    if absent:
        not_estimable.append(
            _ne(
                "NE-BH-REPLAY",
                "Benjamini-Hochberg adjustment cannot be re-derived",
                "data/primary_estimands_31.csv ships no per-estimand two-sided "
                f"p-value (missing columns: {absent}), so the shipped fdr_q values "
                "cannot be recomputed from inputs.",
                affected=list(absent),
                affected_count=EXPECTED_ESTIMANDS,
                denominator=EXPECTED_ESTIMANDS,
                impact="Only the BH family structure (the denominator, which is what "
                "silently changes every q-value if it moves), the [0,1] range and the "
                "2/2001 resolution floor are verified. The adjustment arithmetic "
                "itself is trusted, not reproduced.",
                remedy="Add p_two_sided, occupied_blocks and bootstrap_valid_replicates "
                "to data/primary_estimands_31.csv; the replay then becomes exact via "
                "core.multiple_testing.benjamini_hochberg.",
            )
        )

    sensitivity = validate_locked_sensitivity(primary)
    return {
        "status": "PASS",
        "estimands": len(primary),
        "support_counts": support,
        "bh_family_sizes": families,
        "bh_family_total": sum(families.values()),
        "contract_projection_rows_verified": int(populated.sum()),
        "contract_projection_rows_incomplete": incomplete_ids,
        "fdr_q_range": [float(q_values.min()), float(q_values.max())],
        "fdr_q_resolution_floor": q_floor,
        "point_estimate_inside_own_interval": True,
        "sensitivity": sensitivity,
        "locked_ci_fdr_verified": True,
        "verification_scope": "row-level integrity of the locked ledger; bootstrap "
        "intervals and p-values are not independently recomputed",
        "not_estimable": not_estimable,
    }


# --------------------------------------------------------------------------
# Work package: the minimum analysis input
# --------------------------------------------------------------------------
def _data_qa(data: pd.DataFrame, contract: pd.DataFrame) -> dict[str, object]:
    _require(
        data.shape == EXPECTED_DATA_SHAPE,
        f"Minimum input shape changed: {data.shape}, expected {EXPECTED_DATA_SHAPE}",
    )
    _require(
        data["OasisID"].notna().all() and data["OasisID"].is_unique,
        "OasisID integrity failed",
    )

    # The six excluded identifiers must be absent from the analysis population,
    # and the arithmetic of the exclusion must close.
    identifiers = set(data["OasisID"].astype(str))
    present = sorted(identifiers.intersection(EXCLUDED_IDS))
    _require(
        not present,
        f"Excluded oasis identifiers are present in the analysis table: {present}",
    )
    _require(
        len(data) + len(EXCLUDED_IDS) == HISTORICAL_UNIVERSE,
        f"Exclusion arithmetic does not close: {len(data)} + {len(EXCLUDED_IDS)} "
        f"!= {HISTORICAL_UNIVERSE}",
    )

    class_counts = data["class_label_en"].value_counts().to_dict()
    continent_counts = data["continent5"].value_counts().to_dict()
    _require(class_counts == EXPECTED_CLASS_COUNTS, f"Class counts changed: {class_counts}")
    _require(
        sum(class_counts.values()) == len(data),
        "Koppen class counts do not partition the analysis population",
    )
    _require(
        continent_counts == EXPECTED_CONTINENT_COUNTS,
        f"Continent counts changed: {continent_counts}",
    )
    _require(
        sum(continent_counts.values()) == len(data),
        "Continent counts do not partition the analysis population",
    )

    blocks = validate_block_mapping(data)
    _require(
        blocks["occupied_strict_bwh_bwk"] == EXPECTED_STRICT_BLOCK_COUNTS,
        f"Strict-sample block counts changed: {blocks['occupied_strict_bwh_bwk']}",
    )
    _require(
        blocks["occupied_all"] == EXPECTED_ALL_BLOCK_COUNTS,
        f"All-rows block counts changed: {blocks['occupied_all']}",
    )

    qc_pass = {
        column: int(q_pass(data[column]).sum())
        for column in EXPECTED_QC_PASS
        if column in data.columns
    }
    missing_qc = sorted(set(EXPECTED_QC_PASS) - set(qc_pass))
    _require(not missing_qc, f"QC columns were removed: {missing_qc}")
    _require(qc_pass == EXPECTED_QC_PASS, f"QC pass counts changed: {qc_pass}")

    nex_methods = data["nex_method"].value_counts().to_dict()
    _require(
        nex_methods == EXPECTED_NEX_METHODS, f"NEX method counts changed: {nex_methods}"
    )
    _require(
        sum(nex_methods.values()) == len(data),
        "NEX method counts do not partition the analysis population",
    )

    futurepop = futurepop_accounting(data)
    _require(
        futurepop == EXPECTED_FUTUREPOP,
        f"FuturePop coverage accounting changed: {futurepop}",
    )
    _require(
        futurepop["coverage_gt0"] + futurepop["no_valid"] == len(data),
        "FuturePop coverage accounting does not close against the population",
    )
    # The FuturePop estimands are ungated by design. Assert that the ungated
    # columns are what feeds F04-PRIMARY-22..25, and that each is present.
    missing_futurepop = sorted(set(FUTUREPOP_FIELDS) - set(data.columns))
    _require(not missing_futurepop, f"FuturePop fields were removed: {missing_futurepop}")

    ai_values = pd.to_numeric(data["ai_scaled"], errors="coerce")
    ai_valid = int(ai_values.notna().sum())
    _require(ai_valid == EXPECTED_AI_VALID, f"Scaled AI valid count changed: {ai_valid}")
    low, high = AI_PLAUSIBLE_RANGE
    _require(
        bool(ai_values.dropna().between(low, high).all()),
        f"Scaled AI falls outside the plausible range [{low}, {high}]: "
        f"observed [{ai_values.min()}, {ai_values.max()}]",
    )

    missing_et0 = sorted(set(ET0_FIELDS) - set(data.columns))
    _require(not missing_et0, f"Author-approved ET0 fields were removed: {missing_et0}")
    # Inverted relative to v1.0.0: ET0 is now inside the contract, in the water
    # family, and its removal must fail just as loudly as its unauthorised
    # entry used to.
    contract_by_id = contract.set_index("fact_id")
    for fact_id, source_field in EXPECTED_ET0_ESTIMANDS.items():
        _require(
            fact_id in contract_by_id.index,
            f"ET0 estimand {fact_id} left the contract",
        )
        _require(
            str(contract_by_id.loc[fact_id, "source_field"]) == source_field,
            f"ET0 estimand {fact_id} no longer reads {source_field}",
        )
        _require(
            str(contract_by_id.loc[fact_id, "domain"]) == "water",
            f"ET0 estimand {fact_id} left the water BH family",
        )
    et0_in_contract = sorted(
        contract.loc[contract["source_field"].isin(ET0_FIELDS), "fact_id"].astype(str)
    )
    _require(
        et0_in_contract == sorted(EXPECTED_ET0_ESTIMANDS),
        f"The set of ET0 estimands changed: {et0_in_contract}",
    )

    return {
        "status": "PASS",
        "shape": list(data.shape),
        "oasisid_unique": True,
        "excluded_identifiers_absent": list(EXCLUDED_IDS),
        "historical_universe": HISTORICAL_UNIVERSE,
        "analysis_population": len(data),
        "class_counts": class_counts,
        "continent_counts": continent_counts,
        "spatial_blocks": blocks,
        "qc_pass_counts": qc_pass,
        "nex_methods": nex_methods,
        "futurepop": futurepop,
        "futurepop_gating": "none; futurepop_qc is a coverage diagnostic and is not "
        "an inclusion criterion",
        "ai_scaled_valid": ai_valid,
        "ai_scaled_range": [float(ai_values.min()), float(ai_values.max())],
        "et0": {
            "status": "approved_and_promoted_to_contract",
            "fields_present": list(ET0_FIELDS),
            "qc_pass": qc_pass["et0_qc"],
            "estimands": EXPECTED_ET0_ESTIMANDS,
            "bh_family": "water",
        },
        "not_estimable": [],
    }


# --------------------------------------------------------------------------
# Work package: estimand-contract semantics
# --------------------------------------------------------------------------
def _contract_semantics_qa(data: pd.DataFrame, contract: pd.DataFrame) -> dict[str, object]:
    """Guard the QC-gating contract and the strict-by-default recomputation.

    These two properties are what separate the published effects from a
    rejected sensitivity variant, and neither is visible in any output file, so
    nothing else in the release would catch a regression in them.
    """
    expected_gates = {
        "pop_ssp2_2050": None,
        "pop_ssp2_2080": None,
        "pop_ssp5_2050": None,
        "pop_ssp5_2080": None,
        "pop_density_per_km2_polygon_area": "ghsl_qc",
        "built_s_share_of_polygon_area": "ghsl_qc",
        "ai_scaled": "ai_qc",
        "ever_water_fraction": "jrc_qc",
        "terraclimate_def_1991_2020_mean_annual_mm": "terraclimate_qc",
        "utci_mean_annual_days_max_ge_32c": "utci_qc",
        "nex_ssp245_2041_2070_tasmax_delta_1995_2014_median": "nex_qc",
        "gdp2020_total_analysis_2017_int_usd": "gdp_qc",
        "viirs2020_avg_masked_rad_mean": "viirs_qc",
        "et0_v31_yr_raw_area_weighted_mean_raw": "et0_qc",
    }
    observed = {field: qa_field_for(field) for field in expected_gates}
    _require(
        observed == expected_gates,
        f"qa_field_for mapping changed: "
        f"{ {k: v for k, v in observed.items() if expected_gates[k] != v} }",
    )
    ungated = sorted(field for field, gate in observed.items() if gate is None)
    _require(
        ungated == sorted(FUTUREPOP_FIELDS),
        f"The set of ungated source fields changed: {ungated}",
    )

    unknown_raises = False
    try:
        qa_field_for("__field_that_is_not_registered__")
    except ValueError:
        unknown_raises = True
    _require(
        unknown_raises,
        "qa_field_for no longer raises on an unregistered source field; an "
        "unrecognised field would silently become ungated",
    )

    # Every contract source field must resolve without raising.
    unresolved = []
    for source_field in contract["source_field"].astype(str):
        try:
            qa_field_for(source_field)
        except ValueError as exc:
            unresolved.append({"source_field": source_field, "error": str(exc)})
    _require(not unresolved, f"Contract source fields have no QC mapping: {unresolved}")

    signature = inspect.signature(compute_point_estimands)
    _require(
        "strict" in signature.parameters,
        "compute_point_estimands lost its strict parameter",
    )
    _require(
        signature.parameters["strict"].default is True,
        "compute_point_estimands no longer defaults to strict=True; silent partial "
        "results are exactly how ten estimands failed unnoticed",
    )

    broken_contract = pd.DataFrame(
        [
            {
                "fact_id": "F04-FIXTURE-00",
                "domain": "fixture",
                "estimand": "deliberately_broken_fixture",
                "source_field": "__field_that_is_not_registered__",
                "implementation_method": "median_difference",
            }
        ]
    )
    strict_raised = False
    try:
        compute_point_estimands(data.head(50), broken_contract)
    except RuntimeError:
        strict_raised = True
    _require(
        strict_raised,
        "compute_point_estimands accepted a broken contract row without raising",
    )
    lenient, lenient_failures = compute_point_estimands(
        data.head(50), broken_contract, strict=False
    )
    _require(
        len(lenient) == 0 and len(lenient_failures) == 1,
        "compute_point_estimands(strict=False) no longer reports the failure it "
        "swallowed",
    )

    # The FuturePop estimands must draw the full strict sample. If anyone
    # "fixes" qa_field_for to gate pop_ssp* on futurepop_qc, these collapse.
    futurepop_rows = contract[contract["source_field"].isin(FUTUREPOP_FIELDS)]
    _require(
        len(futurepop_rows) == 4,
        f"Expected 4 FuturePop estimands, found {len(futurepop_rows)}",
    )
    futurepop_sizes = {}
    for row in futurepop_rows.to_dict("records"):
        result = point_result(sample_for_estimand(data, row), row)
        futurepop_sizes[str(row["fact_id"])] = [result["n_bwh"], result["n_bwk"]]
        _require(
            result["n_bwh"] == 1822 and result["n_bwk"] == 742,
            f"FuturePop estimand {row['fact_id']} draws "
            f"n={result['n_bwh']}/{result['n_bwk']}, expected 1822/742. A "
            f"futurepop_qc gate would give roughly 362/71.",
        )

    return {
        "status": "PASS",
        "qa_field_mapping_verified": len(expected_gates),
        "ungated_source_fields": ungated,
        "unknown_source_field_raises": True,
        "compute_point_estimands_strict_default": True,
        "futurepop_sample_sizes": futurepop_sizes,
        "not_estimable": [],
    }


# --------------------------------------------------------------------------
# Work package: release metadata
# --------------------------------------------------------------------------
def _metadata_qa(repo_root: Path, data: pd.DataFrame) -> dict[str, object]:
    """Validate the data dictionary and the third-party redistribution boundary.

    v1.0.0 also asserted a ``public_file_licence`` column and per-field ``role``
    strings. The dictionary schema is now
    ``[field, field_group, description, source_path, baseline_id]``; both of
    those columns are gone, so both assertions were deleted rather than
    rewritten against columns that do not exist.
    """
    not_estimable: list[dict[str, object]] = []

    dictionary = pd.read_csv(repo_root / REQUIRED_FILES["data_dictionary"])
    required_columns = {"field", "field_group", "description", "source_path", "baseline_id"}
    missing_columns = sorted(required_columns - set(dictionary.columns))
    _require(not missing_columns, f"Data dictionary lost columns: {missing_columns}")
    _require(dictionary["field"].is_unique, "Data dictionary has duplicate field rows")
    # The cheapest guard against a 3,443-era dictionary being swapped in.
    baselines = sorted(dictionary["baseline_id"].astype(str).unique())
    _require(
        baselines == [EXPECTED_BASELINE_ID],
        f"Data dictionary baseline_id is not uniformly {EXPECTED_BASELINE_ID}: {baselines}",
    )

    documented = set(dictionary["field"].astype(str))
    columns = set(data.columns)
    undocumented = sorted(columns - documented)
    orphaned = sorted(documented - columns)
    _require(
        not orphaned,
        f"Data dictionary documents fields that are not in the analysis table: {orphaned}",
    )
    if undocumented:
        not_estimable.append(
            _ne(
                "NE-DICTIONARY-COVERAGE",
                "data dictionary does not cover every shipped column",
                f"data/data_dictionary.csv documents {len(dictionary)} fields while "
                f"data/analysis_input_minimal.csv ships {len(columns)} columns.",
                affected=undocumented,
                denominator=len(columns),
                impact="These columns are published without a description, unit or "
                "provenance. block_250km / block_500km / block_1000km are the "
                "spatial-bootstrap clustering keys, so a reuser cannot reconstruct "
                "the clustering from the dictionary alone.",
                remedy=f"Add {len(undocumented)} rows to data/data_dictionary.csv "
                f"with baseline_id={EXPECTED_BASELINE_ID}, then rerun with "
                "strict_ne=True.",
            )
        )

    boundary = pd.read_csv(repo_root / REQUIRED_FILES["third_party_boundary"], dtype=str)
    _require(
        "raw_files_redistributed" in boundary.columns,
        "third_party_product_boundary.csv lost raw_files_redistributed",
    )
    redistributed = boundary["raw_files_redistributed"].str.lower().fillna("")
    _require(
        redistributed.eq("false").all(),
        "A third-party product is marked as raw-data redistributed: "
        + str(boundary.loc[~redistributed.eq("false"), "product_key"].tolist()),
    )

    # A separate file with a different schema. It carries no
    # raw_files_redistributed column, so the redistribution check above must
    # not be pointed at it.
    manifest = pd.read_csv(
        repo_root / REQUIRED_FILES["product_manifest_current"], dtype=str
    )
    manifest_columns = {
        "domain",
        "product",
        "reference_period",
        "analysis_role",
        "validity_boundary",
    }
    missing_manifest = sorted(manifest_columns - set(manifest.columns))
    _require(
        not missing_manifest,
        f"source_product_manifest_current.csv lost columns: {missing_manifest}",
    )
    _require(
        "raw_files_redistributed" not in manifest.columns,
        "source_product_manifest_current.csv unexpectedly grew a "
        "raw_files_redistributed column; the redistribution check reads "
        "third_party_product_boundary.csv and would now be looking at the wrong file",
    )
    _require(len(manifest) == 10, f"Product manifest has {len(manifest)} rows, expected 10")
    _require(len(boundary) == 11, f"Third-party boundary has {len(boundary)} rows, expected 11")

    return {
        "status": "PASS",
        "data_dictionary_rows": len(dictionary),
        "analysis_columns": len(columns),
        "undocumented_columns": undocumented,
        "orphaned_dictionary_rows": orphaned,
        "dictionary_baseline_id": EXPECTED_BASELINE_ID,
        "third_party_products": len(boundary),
        "raw_third_party_files_redistributed": False,
        "product_manifest_rows": len(manifest),
        "mixed_licence_policy": "code=MIT; derived_data_and_documentation=CC-BY-4.0",
        "not_estimable": not_estimable,
    }


# --------------------------------------------------------------------------
# Work package: privacy and retired-artefact hygiene
# --------------------------------------------------------------------------
def _privacy_qa(repo_root: Path) -> dict[str, object]:
    """Scan the shipped text files for leaked paths, addresses and retired names.

    The four regexes are salvaged from v1.0.0's ``_workbook_qa``, which scanned
    Excel cells. The workbook is gone; the scan moved onto the files that
    actually ship.
    """
    surface = _release_surface(repo_root)
    surface_relative = {path.relative_to(repo_root).as_posix() for path in surface}

    privacy_hits: list[dict[str, str]] = []
    retired_hits: list[dict[str, str]] = []
    excluded_id_hits: list[dict[str, str]] = []
    scanned = 0
    scanned_bytes = 0

    for path in surface:
        if not _is_text_file(path):
            continue
        relative = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationFailure(f"{relative} is not valid UTF-8: {exc}") from exc
        scanned += 1
        scanned_bytes += len(text.encode("utf-8"))

        for kind, pattern in PRIVACY_PATTERNS.items():
            for match in pattern.finditer(text):
                privacy_hits.append(
                    {"file": relative, "kind": kind, "match": match.group(0)[:80]}
                )
        if relative not in RETIREMENT_DECLARING_FILES:
            for token in RETIRED_TOKENS:
                if token in text:
                    retired_hits.append({"file": relative, "token": token})
            for label, pattern in RETIRED_TOKEN_PATTERNS.items():
                if pattern.search(text):
                    retired_hits.append({"file": relative, "token": label})
        if relative not in EXCLUSION_DECLARING_FILES:
            for identifier in EXCLUDED_IDS:
                if identifier in text:
                    excluded_id_hits.append({"file": relative, "identifier": identifier})

    _require(not privacy_hits, f"Privacy scan hits: {privacy_hits[:5]}")
    _require(
        not retired_hits,
        f"Retired v1.0.0 artefact names inside the release surface: {retired_hits[:5]}",
    )
    _require(
        not excluded_id_hits,
        f"Excluded oasis identifiers appear in shipped files: {excluded_id_hits[:5]}",
    )

    not_estimable: list[dict[str, object]] = []
    stray_text = sorted(
        path.relative_to(repo_root).as_posix()
        for path in _walk_repository_text_files(repo_root)
        if path.relative_to(repo_root).as_posix() not in surface_relative
    )
    # A spreadsheet in the tree used to be flagged unconditionally, on the
    # assumption that any .xlsx here was the v1.0.0 workbook come back. That is
    # no longer true: the workbook was rebuilt for this population and is a
    # declared release artefact. Undeclared spreadsheets are still stray.
    spreadsheets = sorted(
        path.relative_to(repo_root).as_posix()
        for path in repo_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}
        and not any(
            part in HYGIENE_SKIP_DIRS for part in path.relative_to(repo_root).parts
        )
    )
    stray_binary = [name for name in spreadsheets if name not in surface_relative]
    declared_binary = [name for name in spreadsheets if name in surface_relative]
    if stray_text or stray_binary:
        not_estimable.append(
            _ne(
                "NE-OUTSIDE-RELEASE-SURFACE",
                "files present in the working tree but outside the declared release surface",
                "These files are not covered by the privacy scan, the retired-token "
                "ratchet or the encoding check, because the release does not declare "
                "them as shipped content.",
                affected=stray_text + stray_binary,
                denominator=len(stray_text) + len(stray_binary) + len(surface_relative),
                impact="If any of them is committed, it ships unreviewed.",
                remedy="Either delete them, add them to .gitignore, or add them to "
                "RELEASE_SURFACE_GLOBS so they are scanned. Confirm before committing.",
            )
        )
    if declared_binary:
        not_estimable.append(
            _ne(
                "NE-BINARY-NOT-TEXT-SCANNED",
                "declared spreadsheets cannot be covered by the text-based scans",
                "The privacy scan, the retired-token ratchet and the UTF-8 check read "
                "files as text. A spreadsheet is a ZIP container, so declaring it on "
                "the release surface makes it checksummed and inventoried but does "
                "not subject its cell contents to those three scans.",
                affected=declared_binary,
                denominator=len(surface_relative),
                impact="A stale label, an absolute path or an author name inside a "
                "worksheet cell would not be caught here. Every number the workbook "
                "carries is generated by scripts/build_source_data_workbook.py from "
                "the same release inputs this validator checks, so a value that "
                "disagrees with the ledger is still caught upstream; free text is not.",
                remedy="Unpack the workbook XML and scan it, or re-run "
                "scripts/build_source_data_workbook.py and diff, before tagging a "
                "release that mints a DOI.",
            )
        )

    return {
        "status": "PASS",
        "release_surface_files": len(surface_relative),
        "text_files_scanned": scanned,
        "bytes_scanned": scanned_bytes,
        "privacy_hits": privacy_hits,
        "retired_token_hits": retired_hits,
        "excluded_identifier_hits": excluded_id_hits,
        "files_outside_release_surface": stray_text + stray_binary,
        "not_estimable": not_estimable,
    }


# --------------------------------------------------------------------------
# Work package: text encoding
# --------------------------------------------------------------------------
def _encoding_qa(repo_root: Path) -> dict[str, object]:
    """Strict UTF-8 read-back of every shipped text file.

    Hard failures: undecodable UTF-8, a lone carriage return, or a byte-order
    mark in a ``.py`` / ``.yml`` file (where it breaks tooling). A BOM on a CSV
    is reported, not failed: several shipped tables carry one deliberately so
    that Excel renders their non-ASCII content correctly, and pandas strips it.
    """
    per_file: dict[str, dict[str, object]] = {}
    special_totals = {name: 0 for name in SPECIAL_CHARACTERS}
    bom_csv: list[str] = []
    for path in _release_surface(repo_root):
        if not _is_text_file(path):
            continue
        relative = path.relative_to(repo_root).as_posix()
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        _require(
            not (has_bom and path.suffix.lower() in {".py", ".yml", ".yaml"}),
            f"{relative} starts with a UTF-8 BOM, which breaks source and config parsing",
        )
        _require(
            b"\r" not in raw.replace(b"\r\n", b""),
            f"{relative} contains a lone carriage return",
        )
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationFailure(f"{relative} is not valid UTF-8: {exc}") from exc
        # Round-trip: re-encoding must reproduce the exact bytes, so no special
        # character was mangled on the way in.
        _require(
            text.encode("utf-8") == raw,
            f"{relative} does not round-trip through UTF-8",
        )
        specials = {
            name: text.count(character)
            for name, character in SPECIAL_CHARACTERS.items()
            if text.count(character)
        }
        for name, count in specials.items():
            special_totals[name] += count
        if has_bom:
            bom_csv.append(relative)
        record: dict[str, object] = {
            "bytes": len(raw),
            "utf8": True,
            "bom": has_bom,
            "crlf": b"\r\n" in raw,
            "non_ascii_characters": sum(1 for character in text if ord(character) > 127),
        }
        if specials:
            record["special_characters"] = specials
        per_file[relative] = record

    # The first column name must survive BOM stripping, which is the only way a
    # BOM could actually corrupt an analysis.
    for name in ("estimand_contract", "primary_estimands"):
        frame = pd.read_csv(repo_root / REQUIRED_FILES[name], nrows=1)
        _require(
            str(frame.columns[0]) == "fact_id",
            f"{REQUIRED_FILES[name]} first column parses as {frame.columns[0]!r}, "
            "not 'fact_id'; a byte-order mark is leaking into the header",
        )

    return {
        "status": "PASS",
        "files_checked": len(per_file),
        "encoding": "utf-8",
        "byte_order_marks_present": bom_csv,
        "byte_order_mark_policy": "rejected in .py/.yml; reported but allowed in .csv, "
        "where it is deliberate for Excel compatibility and stripped by pandas",
        "special_character_totals": special_totals,
        "per_file": per_file,
        "not_estimable": [],
    }


# --------------------------------------------------------------------------
# Top-level orchestrator
# --------------------------------------------------------------------------
def validate_repository(
    repo_root: Path,
    output_dir: Path,
    *,
    resume: bool = False,
    strict_ne: bool = False,
) -> dict[str, Any]:
    """Verify the release and write a machine-readable receipt.

    Writes ``reproduction_QA.json``, ``reproduction_state.json``,
    ``reproduction.log`` and ``regenerated_point_estimands_31.csv`` into
    ``output_dir``, which defaults outside the repository so verification
    never dirties the working tree.

    ``strict_ne=True`` promotes every not-estimable record into a hard
    failure. Use it once the gaps each record names have been closed.
    """
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()

    files = {name: repo_root / relative for name, relative in REQUIRED_FILES.items()}
    missing = [
        str(path.relative_to(repo_root)) for path in files.values() if not path.is_file()
    ]
    _require(not missing, f"Required repository files are missing: {missing}")
    input_hashes = {name: sha256(path) for name, path in files.items()}

    implementation_paths = [
        repo_root / "environment.yml",
        repo_root / "scripts/reproduce.py",
        *sorted((repo_root / "code" / "core").glob("*.py")),
        *sorted((repo_root / "tests").glob("*.py")),
    ]
    implementation_missing = [
        str(path.relative_to(repo_root))
        for path in implementation_paths
        if not path.is_file()
    ]
    _require(
        not implementation_missing,
        f"Implementation files are missing: {implementation_missing}",
    )

    resume_fingerprint = dict(input_hashes)
    resume_fingerprint.update(
        {
            f"implementation:{path.relative_to(repo_root).as_posix()}": sha256(path)
            for path in implementation_paths
        }
    )
    if resume:
        resumed = _resume_result(output_dir, resume_fingerprint)
        if resumed is not None:
            return resumed

    config = yaml.safe_load(files["analysis_config"].read_text(encoding="utf-8"))
    contract = pd.read_csv(files["estimand_contract"])
    data = pd.read_csv(files["minimum_input"], low_memory=False)
    primary = pd.read_csv(files["primary_estimands"])

    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "reproduction_state.json"
    log_path = output_dir / "reproduction.log"
    work_names = (
        "point_estimands",
        "point_integrity",
        "locked_outputs",
        "minimum_input",
        "contract_semantics",
        "metadata",
        "privacy",
        "encoding",
        "integrity",
        "configuration",
    )
    previous_state = _load_interrupted_state(state_path, resume_fingerprint, resume)
    continuing = previous_state is not None
    if previous_state is None:
        state: dict[str, Any] = {
            "status": "running",
            "input_sha256": input_hashes,
            "resume_fingerprint_sha256": resume_fingerprint,
            "work_packages": {
                name: {
                    "status": "pending",
                    **(
                        {
                            "items": {
                                str(row["fact_id"]): {
                                    "status": "pending",
                                    "estimand": str(row["estimand"]),
                                }
                                for row in contract.to_dict("records")
                            }
                        }
                        if name == "point_estimands"
                        else {}
                    ),
                }
                for name in work_names
            },
            "outputs": {},
        }
        atomic_bytes(log_path, b"")
    else:
        state = previous_state
        state["status"] = "running"
        for name in work_names:
            state.setdefault("work_packages", {}).setdefault(name, {"status": "pending"})
        state["work_packages"]["point_estimands"].setdefault("items", {})
    atomic_json(state_path, state)
    _append_log(log_path, f"validation running resume={continuing}")

    def run_step(name: str, function: Any) -> dict[str, object]:
        work = state["work_packages"][name]
        result_path = output_dir / "step_results" / f"{name}.json"
        if (
            resume
            and work.get("status") == "success"
            and result_path.is_file()
            and work.get("result_sha256") == sha256(result_path)
        ):
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                _append_log(log_path, f"step resumed {name}")
                return result
            except (OSError, json.JSONDecodeError):
                pass
        work["status"] = "running"
        state["status"] = "running"
        atomic_json(state_path, state)
        _append_log(log_path, f"step running {name}")
        try:
            result = function()
            atomic_json(result_path, result)
            work.update(
                {"status": "success", "result_sha256": sha256(result_path), "error": None}
            )
            atomic_json(state_path, state)
            _append_log(log_path, f"step success {name}")
            return result
        except Exception as exc:
            work.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            state["status"] = "failed"
            atomic_json(state_path, state)
            _append_log(log_path, f"step failed {name} {type(exc).__name__}: {exc}")
            raise

    regenerated, point_failures, resumed_estimators = _resumable_point_estimands(
        data, contract, output_dir, state, log_path, resume=resume
    )
    point_qa = run_step(
        "point_integrity",
        lambda: _point_estimate_qa(regenerated, point_failures, primary, resumed_estimators),
    )
    locked_qa = run_step("locked_outputs", lambda: _locked_output_qa(contract, primary))
    data_qa = run_step("minimum_input", lambda: _data_qa(data, contract))
    semantics_qa = run_step(
        "contract_semantics", lambda: _contract_semantics_qa(data, contract)
    )
    metadata_qa = run_step("metadata", lambda: _metadata_qa(repo_root, data))
    privacy_qa = run_step("privacy", lambda: _privacy_qa(repo_root))
    encoding_qa = run_step("encoding", lambda: _encoding_qa(repo_root))

    def integrity_step() -> dict[str, object]:
        result, records = _integrity_qa(repo_root, input_hashes)
        return {**result, "not_estimable": records}

    integrity_qa = run_step("integrity", integrity_step)

    def configuration_qa() -> dict[str, object]:
        """Cross-check config/analysis.yml against the data, not against literals.

        The v1.0.0 version read ``config['expected']['estimands']``,
        ``config['expected']['numeric_facts']`` and
        ``config['aridity_index']['scale_factor']``. The file is flat now and
        has none of those key paths, so this is a rewrite rather than an edit.
        Cross-checking against the data is what catches a config left behind
        after a data regeneration.
        """
        not_estimable: list[dict[str, object]] = []
        required_keys = {
            "project",
            "analysis_population",
            "excluded_identifiers",
            "analysis_regions",
            "comparison",
            "primary_block_km",
            "sensitivity_block_km",
            "multiple_testing",
            "estimands",
            "ai_scale_factor",
            "third_party_raw_data_redistributed",
        }
        missing_keys = sorted(required_keys - set(config))
        _require(not missing_keys, f"config/analysis.yml lost keys: {missing_keys}")

        _require(
            config["estimands"] == len(contract) == len(primary) == EXPECTED_ESTIMANDS,
            f"Configured estimand count {config['estimands']} disagrees with the "
            f"contract ({len(contract)}) or the ledger ({len(primary)})",
        )
        _require(
            config["analysis_population"] == len(data) == ANALYSIS_POPULATION,
            f"Configured analysis population {config['analysis_population']} disagrees "
            f"with the shipped table ({len(data)})",
        )
        _require(
            config["excluded_identifiers"] == len(EXCLUDED_IDS),
            f"Configured exclusion count {config['excluded_identifiers']} disagrees "
            f"with the {len(EXCLUDED_IDS)} identifiers this validator enforces",
        )
        _require(
            config["analysis_population"] + config["excluded_identifiers"]
            == HISTORICAL_UNIVERSE,
            "Configured population and exclusions do not sum to the historical universe",
        )
        _require(
            set(config["analysis_regions"]) == set(data["continent5"].unique()),
            f"Configured regions {sorted(config['analysis_regions'])} disagree with the "
            f"table {sorted(data['continent5'].unique())}",
        )
        _require(
            config["ai_scale_factor"] == EXPECTED_AI_SCALE_FACTOR,
            f"AI scale factor changed: {config['ai_scale_factor']}",
        )
        _require(
            config["primary_block_km"] == 500,
            f"Primary block scale changed: {config['primary_block_km']}",
        )
        _require(
            sorted(config["sensitivity_block_km"]) == [250, 1000],
            f"Sensitivity block scales changed: {config['sensitivity_block_km']}",
        )
        _require(
            config["third_party_raw_data_redistributed"] is False,
            "Configuration claims third-party raw data is redistributed",
        )
        boundary = pd.read_csv(
            repo_root / REQUIRED_FILES["third_party_boundary"], dtype=str
        )
        _require(
            boundary["raw_files_redistributed"].str.lower().eq("false").all(),
            "Configuration and third_party_product_boundary.csv disagree on "
            "raw-data redistribution",
        )
        _require(
            "Benjamini-Hochberg" in str(config["multiple_testing"]),
            f"Multiple-testing policy changed: {config['multiple_testing']}",
        )
        return {
            "status": "PASS",
            "project": config["project"],
            "estimands": config["estimands"],
            "analysis_population": config["analysis_population"],
            "excluded_identifiers": config["excluded_identifiers"],
            "analysis_regions": list(config["analysis_regions"]),
            "primary_block_km": config["primary_block_km"],
            "sensitivity_block_km": list(config["sensitivity_block_km"]),
            "ai_scale_factor": config["ai_scale_factor"],
            "third_party_raw_data_redistributed": False,
            "cross_checked_against_data": True,
            "not_estimable": not_estimable,
        }

    configuration = run_step("configuration", configuration_qa)

    atomic_csv(output_dir / "regenerated_point_estimands_31.csv", regenerated)

    sections = {
        "point_estimates": point_qa,
        "locked_outputs": locked_qa,
        "minimum_input": data_qa,
        "contract_semantics": semantics_qa,
        "metadata": metadata_qa,
        "privacy": privacy_qa,
        "encoding": encoding_qa,
        "integrity": integrity_qa,
        "configuration": configuration,
    }
    not_estimable: list[dict[str, object]] = []
    for section_name, section in sections.items():
        for record in section.get("not_estimable", []) or []:
            not_estimable.append({"work_package": section_name, **record})

    if strict_ne and not_estimable:
        raise ValidationFailure(
            f"{len(not_estimable)} not-estimable record(s) under strict_ne: "
            + "; ".join(f"{record['code']} ({record['subject']})" for record in not_estimable)
        )

    status = "PASS" if not not_estimable else "PASS_WITH_NE"
    support = locked_qa["support_counts"]
    qa: dict[str, Any] = {
        "status": status,
        "resumed": continuing,
        "repository": "global-oasis-exposure",
        "analysis_baseline": EXPECTED_BASELINE_ID,
        "input_sha256": input_hashes,
        "resume_fingerprint_sha256": resume_fingerprint,
        **sections,
        "not_estimable": not_estimable,
        "summary": {
            "analysis_population": len(data),
            "excluded_identifiers": len(EXCLUDED_IDS),
            "historical_universe": HISTORICAL_UNIVERSE,
            "estimands": EXPECTED_ESTIMANDS,
            "estimands_recomputed": int(point_qa["regenerated"]),
            "robust": support.get("robust", 0),
            "sensitive": support.get("sensitive", 0),
            "not_supported": support.get("not_supported", 0),
            "bootstrap_recomputed": False,
            "reproduction_boundary": "point estimates recomputed from the shipped "
            "table and matched row by row; 95% intervals and FDR q-values are "
            "verified against the locked ledger, not re-drawn",
            "not_estimable_records": len(not_estimable),
        },
    }
    atomic_json(output_dir / "reproduction_QA.json", qa)
    _append_log(log_path, f"validation {status} ne={len(not_estimable)}")
    state["status"] = status
    state["outputs"] = {
        "regenerated_point_estimands_31.csv": sha256(
            output_dir / "regenerated_point_estimands_31.csv"
        ),
        "reproduction_QA.json": sha256(output_dir / "reproduction_QA.json"),
        "reproduction.log": sha256(log_path),
    }
    atomic_json(output_dir / "reproduction_state.json", state)
    return qa
