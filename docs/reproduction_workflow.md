# Reproduction workflow

**Release:** global oasis exposure — 3,437-oasis analysis
**Baseline identifier:** `analysis_release_3437` (carried by every shipped record)

This document states what a third party can verify from the files in this
repository, the exact commands to do it, and — in the same level of detail —
what this repository does **not** allow anyone to verify. Every claim below was
checked against the shipped files. Where something could not be established
from the shipped files, it is written as a limitation rather than softened.

---

## 1. Status at a glance

| Quantity | Status from this repository alone |
|---|---|
| Analysis population: 3,437 oases × 219 columns | Verifiable |
| All 31 primary **point** estimates | **Fully reproducible** — recomputed from the shipped table and matched row by row |
| Per-estimand sample sizes `n_bwh` / `n_bwk` | Fully reproducible |
| Spatial-block structure at 250 / 500 / 1,000 km | Verifiable |
| Benjamini–Hochberg family structure (the q-value denominators) | Verifiable |
| Locked 95 % bootstrap intervals | **Not bit-reproducible for 10 of the 31 estimands** — see §6.1 |
| Benjamini–Hochberg q-values | Structure, range and resolution floor only; the adjustment arithmetic cannot be replayed — see §6.2 |
| `data/analysis_input_minimal.csv` itself | **Not regenerable** from this repository — see §6.4 |
| Third-party rasters, NetCDF products, oasis boundary geometries | Not redistributed; out of scope here — see §6.5 |

---

## 2. What the release contains

```
config/analysis.yml                     design constants
config/estimands_31.csv                 the estimand contract (31 rows)
data/analysis_input_minimal.csv         3,437 rows × 219 columns
data/primary_estimands_31.csv           the locked result ledger (31 rows)
data/data_dictionary.csv                field-level documentation (213 fields)
data/source_product_manifest_current.csv    source-product manifest (10 rows)
data/third_party_product_boundary.csv   redistribution boundary (11 rows)
data/Source_Data_CEE_v1.xlsx            figure/table source-data workbook (35 sheets)
code/core/*.py                          non-graphical analysis modules
scripts/reproduce.py                    the verifier entry point
tests/verify_current_minimum.py         the minimum standalone check
```

Design constants, for orientation:

- Analysis population **3,437** oases, formed by removing 6 identifiers from a
  3,443-oasis historical universe. All 6 belong to the non-BW class, so the
  strict contrast is unchanged by the exclusion.
- Class composition: BWh 1,822; BWk 742; mixed BWh/BWk 131; non-BW 742.
- Continents: Asia 1,587; Africa 1,096; North America 591; South America 123;
  Oceania 40.
- Primary comparison: **BWh oases minus BWk oases**, n = 1,822 versus 742
  (2,564 polygons in the strict contrast), identical for all 31 estimands.
- **31** primary estimands, `F04-PRIMARY-01` … `F04-PRIMARY-31`, in six
  Benjamini–Hochberg families: `social` 2, `water` 5, `utci` 4, `nex` 12,
  `futurepop` 4, `economic_nightlights` 4.
- Four estimator methods: `median_difference` (19), `median_log_ratio` (5),
  `area_weighted_mean_difference` (5), `population_weighted_mean_difference` (2).
  The patch-median estimator takes the **lower** of the two central values for
  an even class size.
  The `statistic` column of `data/primary_estimands_31.csv` shows **five**
  distinct values rather than four, because it names the four FuturePop rows
  `patch_median_difference` where the contract's `implementation_method` calls
  them `median_difference`. These are the same estimator: `statistic` is the
  descriptive name of the quantity, `implementation_method` is the dispatch key
  the code computes it with. 15 + 4 = 19 reconciles the two counts.
- Inference: occupied-block cluster bootstrap at **500 km**, over **148**
  occupied blocks in the strict contrast (BWh 115, BWk 52, shared 19),
  **B = 2,000** valid replicates, **0** invalid resamples.
- Scale sensitivity at **250 km** (352 occupied blocks) and **1,000 km**
  (65 occupied blocks), 1,000 replicates each, extended to 2,000 for the 5 runs
  whose interval support changed between 1,000 and the full draw.
- Support classification of the locked ledger: 23 `robust`, 2 `sensitive`,
  6 `not_supported`.
- Units appearing in the ledger include days yr⁻¹, mm yr⁻¹, persons km⁻²,
  °C, and log ratios; per-field units are in `data/data_dictionary.csv`.
  The thermal-stress estimands are annual day counts named by their thresholds:
  `utci_mean_annual_days_max_ge_32c` (daily maximum UTCI ≥ 32 °C) and
  `utci_mean_annual_days_min_le_minus13c` (daily minimum UTCI ≤ −13 °C).

---

## 3. Environment

The pinned reference environment is `environment.yml`:

```
python=3.12.13  numpy=2.3.5  pandas=2.3.3  openpyxl=3.1.5  pyyaml=6.0.3
```

```bash
conda env create -f environment.yml
conda activate global-oasis-exposure
```

The point-estimate check is exact arithmetic compared under a tolerance, so it
is not fragile across minor version drift. Bit-level agreement of bootstrap
intervals is only claimed under the pinned stack; a different NumPy or Python
build is not guaranteed to reproduce quantiles to the last digit.

---

## 4. Running the verification

Two commands. Run them from the repository root.

### 4.1 Minimum standalone check

```bash
python tests/verify_current_minimum.py
```

This loads the shipped table and the estimand contract, recomputes **all 31
point estimands** with `code/core/estimands.py`, and compares each against
`data/primary_estimands_31.csv`. It is strict: any estimand that fails to
compute raises rather than being dropped from a short results frame. Expected
output:

```
PASS: 3437 rows; 31 primary estimand records; 31/31 point estimates recomputed
and matched to <= 1e-09 relative
```

### 4.2 Full release verification with a machine-readable receipt

```bash
python scripts/reproduce.py
```

Options:

```bash
python scripts/reproduce.py --output-dir <dir>   # receipt location
python scripts/reproduce.py --resume             # continue an interrupted run
python scripts/reproduce.py --strict-ne          # treat every NE record as a failure
python scripts/reproduce.py --write-sums         # (re)pin SHA256SUMS.txt
python scripts/reproduce.py --full-bootstrap     # also re-draw the cluster bootstrap
```

By default the receipt is written to `<repo>/../reproduction_output`, i.e.
*outside* the repository, so verifying never dirties the working tree. Three
files are produced: `reproduction_QA.json` (the receipt),
`reproduction_state.json` (resume state) and `reproduction.log`.

Note that `code/` cannot be imported as a package: the Python standard library
ships a module named `code`, which shadows the directory. `scripts/reproduce.py`
puts `code/` on `sys.path` and imports `core.<module>`; that is the supported
import route.

---

## 5. What the default path actually proves

The default path recomputes and cross-checks:

- **Point estimates.** All 31 recomputed from `data/analysis_input_minimal.csv`
  and matched against the locked ledger at `rtol = atol = 1e-10`, together with
  `estimate_bwh`, `estimate_bwk`, `effect_bwh_minus_bwk` and the per-estimand
  `n_bwh` / `n_bwk`. The sample-size check is the one that catches a
  quality-gate regression, which would leave the arithmetic superficially valid
  while silently changing the sample.
- **Population integrity.** Row count, `OasisID` uniqueness, absence of the six
  excluded identifiers, and closure of the exclusion arithmetic against the
  historical universe.
- **Composition.** Köppen class counts and continent counts, each asserted to
  partition the population.
- **Spatial blocks.** The `EE8857_{scale}km_{i}_{j}` identifier hierarchy
  (parent = child // 2) at all three scales, with no nulls, plus the occupied
  block counts.
- **Quality-control accounting.** Per-column pass counts, the NEX method split
  (2,865 polygon reducer / 572 representative-point fallback), and the
  future-population coverage accounting, each checked to close against 3,437.
- **Contract semantics.** That the quality-gate mapping is unchanged, that an
  unregistered source field raises rather than defaulting to ungated, and that
  the recomputation is strict by default.
- **Locked-ledger internal consistency.** Fact-ID identity and order, uniform
  baseline identifier, support-class tally, Benjamini–Hochberg family sizes
  summing to 31, every point estimate lying inside its own interval, every
  q-value inside [0, 1], and no q-value below the 2/2001 resolution floor
  implied by 2,000 replicates.
- **Metadata and hygiene.** Data-dictionary schema and coverage, the
  redistribution boundary (no third-party raw file marked as redistributed),
  UTF-8 validity and byte round-tripping of every shipped text file, absence of
  absolute filesystem paths and e-mail addresses, and absence of retired
  artefact names.

On the shipped files this returns `PASS_WITH_NE` — every check passes, and six
checks that *cannot* be evaluated are reported explicitly rather than skipped
(see §7).

---

## 6. What this release cannot verify

### 6.1 Locked confidence intervals are not bit-reproducible for 10 of 31 estimands

This is the most important limitation in the release, and it is a hard one.

`code/core/bootstrap.py` seeds each bootstrap deterministically:

```python
def stable_seed(run_key: str, base_seed: int = 20260710) -> int:
    digest = hashlib.sha256(f"{base_seed}:{run_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)
```

The seed therefore depends on the **exact `run_key` string**. The orchestration
in `code/core/inference.py` builds that string as
`main__{domain}__{estimand}__500km` for the primary runs and
`scale__{domain}__{estimand}__{scale}km` for the scale checks.

**21 of the 31 locked primary runs used exactly that default form. The other 10
did not.** Four UTCI estimands, four future-population estimands and two
reference-evapotranspiration estimands were run under a different `run_key`
prefix, inherited from the working-directory task identifiers of the analysis
run that produced them. Those task keys are recorded only in an internal
bootstrap-detail file that is **not part of this release**, and they are not
derivable from any shipped column.

Consequences, stated plainly:

- Every one of the 31 **point** estimates reproduces exactly. The `run_key`
  affects only the resampling stream, never the estimator.
- For the 21 estimands whose locked key matches the default form, re-running the
  bootstrap reproduces the locked interval to floating-point noise. Verified
  example, `F04-PRIMARY-01`: the default key yields seed 14832313866629215436,
  148 occupied blocks, 2,000/2,000 valid replicates and an interval matching the
  ledger to 5.6 × 10⁻¹⁷ — a CSV round-trip artefact, not a disagreement.
- For the other **10** estimands, re-running with the default key produces a
  different seed and therefore a different, statistically equivalent but not
  identical, interval. Verified example, `F04-PRIMARY-30` (reference
  evapotranspiration, mm yr⁻¹): the interval bounds move by roughly 3.7 and
  4.7 mm yr⁻¹ against a locked interval spanning about 323 mm yr⁻¹. Supplying
  the locked key restores agreement to 4.5 × 10⁻¹³.
- Because Benjamini–Hochberg adjustment is applied **within domain**, the
  q-values of the whole `utci` (4), `futurepop` (4) and `water` (5) families —
  13 estimands — may shift if those families are re-drawn, including the three
  `water` estimands whose own keys are the default form.

No claim is made here that a third party can regenerate the locked intervals
byte-for-byte. A third party can regenerate intervals that are statistically
indistinguishable from them, and can reproduce every point estimate exactly.

### 6.2 The Benjamini–Hochberg adjustment cannot be replayed

`data/primary_estimands_31.csv` ships no per-estimand two-sided p-value, and no
`occupied_blocks` or `bootstrap_valid_replicates` column. The shipped `fdr_q`
values therefore cannot be recomputed from released inputs. What *is* verified:
the family structure (the denominator, which is what silently moves every
q-value if it changes), the [0, 1] range, and the 2/2001 resolution floor. The
adjustment arithmetic itself is trusted, not reproduced.

### 6.3 The default path does not re-draw the bootstrap

`ci95_low`, `ci95_high` and `fdr_q` are checked for internal consistency against
the locked ledger, not independently re-derived. This is printed to the console
on every run, not only recorded in the receipt. Use `--full-bootstrap` to
re-derive them, and read §6.1 first for what the result will and will not match.

### 6.4 The shipped analysis table cannot be regenerated from this repository

`code/core/prepare_inputs.py` requires two inputs that are **not** in this
release: an upstream unified source table and a block-mapping table. It also
selects a 44-column subset, whereas the shipped
`data/analysis_input_minimal.csv` carries 219 columns. Running it would not
reproduce the released file. It is shipped so the column-selection logic is
inspectable, not as a build step.

### 6.5 Upstream products and geometries are out of scope

No third-party raster, NetCDF file, archive or oasis boundary geometry is
redistributed. Raster overlays, zonal statistics and geometry repair are
therefore not reproducible here; the release begins at the polygon-summary
table. `data/third_party_product_boundary.csv` and
`data/source_product_manifest_current.csv` record provider, version, access
route, citation and licence terms for each product. Geometries are available
from the published oasis boundary dataset (doi:10.3974/geodp.2025.03.01) and
join to this release on `OasisID`.

### 6.6 `code/core/sensitivity.py` is not an analysis module

Despite the name, it contains no sensitivity analysis. It re-derives a support
class from an existing ledger row, checks that the `sensitivity_summary` string
mentions the two sensitivity scales, and counts future-population coverage. The
sensitivity *analysis* lives in `code/core/inference.py`; the numeric scale
results live in the Source Data workbook (§8).

### 6.7 No pinned checksum baseline ships yet

`SHA256SUMS.txt` is absent from the working tree at the time of writing, so
file-level tamper detection by digest comparison is unavailable. Every content
check in the verifier runs against file contents independently of digests, so
corruption that changes a checked value is still caught. Pin the baseline last,
after every shipped file is final:

```bash
python scripts/reproduce.py --write-sums
```

---

## 7. Re-drawing the bootstrap yourself

```bash
python scripts/reproduce.py --full-bootstrap
```

This runs the complete orchestration: 500 km primary → 250/1,000 km scale
sensitivity → alternative-specification checks → NEX polygon-only variant →
area long-tail variant → Benjamini–Hochberg → support classification → a
comparison against the locked ledger. It is slow and opt-in by design, because
an approved locked inference must not be silently replaced.

**Expect the locked comparison to report differences.** The comparison is made
at `rtol = atol = 1e-10` on `ci95_low`, `ci95_high` and `fdr_q`. For the reasons
in §6.1, the 10 estimands with non-default locked keys will not match at that
tolerance, and the q-values of the three affected families may not either. This
is a consequence of an unpublished seed string, not of a data or code defect:
the point estimates and sample sizes in the same comparison do match exactly.
Read a `--full-bootstrap` disagreement in `ci95_*` or `fdr_q` as
"different resampling stream", and a disagreement in `n_bwh`, `n_bwk`,
`estimate_bwh`, `estimate_bwk` or `effect_bwh_minus_bwk` as a real failure.

The released driver also does not regenerate the locked
alternative-specification ledger. `ALTERNATIVE_METHODS` in
`code/core/inference.py` covers 7 estimands and `AREA_LONG_TAIL_ESTIMANDS`
covers 3; adding the NEX polygon-only variant for the 12 `nex` estimands gives
22 alternative-specification rows. The `sensitivity_summary` column of
`data/primary_estimands_31.csv` references **26** such checks across 21
estimands. The released driver reproduces a subset, not the locked set.

---

## 8. Spatial-scale sensitivity results

The prose `sensitivity_summary` column of `data/primary_estimands_31.csv`
carries booleans only (`direction_agrees`, `support_agrees`). The **numeric**
250 km and 1,000 km intervals are published in
`data/Source_Data_CEE_v1.xlsx`, sheet `SuppTableS8_ScaleSensitivity`: per
estimand, the occupied block count, 95 % interval, valid and invalid replicate
counts, and the direction/support agreement flags at each scale, alongside the
500 km primary interval and q-value. Each cell carries a `ci_source_*` column
naming its origin.

Summary of that evidence: all 62 scale runs (31 estimands × 2 scales) agree in
direction with the 500 km primary; 4 of 62 disagree on interval support, and
those four are exactly what produced the `sensitive` and `not_supported`
labels. Invalid resamples: 0 in all runs, at every scale.

---

## 9. The Source Data workbook

`data/Source_Data_CEE_v1.xlsx` holds 35 sheets of source data for the figures,
main tables and supplementary tables. Every polygon-level sheet has exactly
3,437 rows; `Table2_Estimands` is a one-to-one copy of
`data/primary_estimands_31.csv` with the support rule recomputed at build time.
Its `README` sheet records the population, denominators, estimator definitions,
unit conventions and — explicitly — every sheet and column that was *not*
created, with the reason. Blank cells mean not estimable under the stated
validity rule; they are never zeros.

The workbook is rebuilt by `scripts/build_source_data_workbook.py`, which
hard-codes no numeric value: every number on a data sheet is read or computed
from the release inputs plus the locked 250/1,000 km intervals. That locked
interval pack is not redistributed and no path to it is stored in this
repository, so the workbook build is not runnable from a fresh clone. The
workbook itself is shipped, so its contents remain inspectable.

---

## 10. Not-estimable reporting policy

A check that cannot be evaluated is never silently skipped and never relaxed
into a weaker check that happens to pass. It becomes an explicit not-estimable
record naming the subject, the reason, the affected items, the denominator, the
consequence and the remedy. These appear under `not_estimable` in
`reproduction_QA.json` and are printed by `scripts/reproduce.py`. Six are open
on the current tree: the ratio column absent from the ledger, the estimand
contract leaving 9 descriptive columns empty for 10 rows, the
Benjamini–Hochberg replay (§6.2), 6 of 219 columns undocumented in the data
dictionary, files present in the tree but outside the declared release surface,
and the absent checksum baseline (§6.7).

Once the underlying gaps are closed, run with `--strict-ne` to promote every
such record into a hard failure.

---

## 11. Licensing and citation

Code is MIT; derived data and documentation are CC BY 4.0. Neither licence
grants any right in third-party source products. See `LICENSE`, `LICENSE-DATA`
and `THIRD_PARTY_NOTICES.md`. Citation metadata is in `CITATION.cff`.
