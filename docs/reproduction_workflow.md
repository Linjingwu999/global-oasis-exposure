# Reproduction workflow

## What the default command verifies

`python scripts/reproduce.py --resume` performs a clean, path-independent verification using only files in this repository. It:

1. checks the 3,443-row, 44-field minimum input and unique oasis identifiers;
2. verifies the four public class counts and five-continent aggregation;
3. validates the nested 250, 500, and 1,000 km Equal Earth spatial-block identifiers;
4. recomputes all 21 BWh-versus-BWk point estimates using the registered QA filters and weights;
5. integrity-checks the authoritative locked confidence intervals, domain-wise Benjamini-Hochberg q-values, and 250/1,000 km sensitivity records by exact SHA-256 and row-level contracts;
6. verifies the exact 16 robust / 2 sensitive / 3 not-supported split and 29 accepted facts;
7. independently rebuilds the four FuturePop class totals and coverage denominators;
8. verifies AI scaling safeguards, UTCI completeness, NEX extraction modes, and ET0 retention boundaries;
9. opens every Source Data worksheet and checks required sheets, formulas, private contact details, and local paths.

Outputs are written to a sibling directory by default, so a successful run does not dirty the repository. Use `--output-dir PATH` to select another destination. With `--resume`, a previous PASS is reused only if every required input hash is unchanged.

The default run checkpoints each point estimand independently, atomically writes partial results and state after every estimator, continues unrelated estimators after an individual failure, and records an execution log in the output directory. A resumed run reuses only successful estimator or validation-step results whose hashes and complete code/data/environment fingerprint still match.

## Locked bootstrap contract

The inferential contract used an occupied-block cluster bootstrap with:

- 500 km Equal Earth blocks for the primary analysis;
- 2,000 valid replicates per estimand;
- deterministic per-task seeds derived from SHA-256 of the base seed and task key;
- 95% percentile intervals and two-sided bootstrap p-values with a +1 correction;
- Benjamini-Hochberg false-discovery-rate adjustment within four domains of sizes 2, 3, 4, and 12;
- 250 and 1,000 km block-scale sensitivity checks.

The released `src/bootstrap.py` implements this procedure with atomic checkpoints and resume support. The default verifier intentionally does not rerun those 42,000 primary bootstrap effects or replace the locked inferential results. Instead, it recomputes the deterministic point estimates from the released minimum table; verifies exact authoritative hashes and per-estimand contracts for the locked confidence intervals, q-values, and sensitivity records; and reproduces the support-class rule from those locked records. This preserves the approved statistical contract while making the implementation inspectable. It is an integrity verification of locked inference, not an independent recomputation of bootstrap p-values, intervals, or FDR q-values.

## Optional bootstrap reuse

Advanced users may import `sample_for_estimand` from `src.estimands` and `cluster_bootstrap` from `src.bootstrap`. A caller must supply the exact task key, scale, target-valid count, and an external checkpoint path. Optional runs should be treated as independent checks, not as replacements for the released locked results unless the full pre-specified orchestration and extension rules are also followed.

For the complete pre-specified orchestration, run `python scripts/reproduce.py --resume --full-bootstrap`. This opt-in route includes the 21 primary 500 km tasks, conditional 5,000-replicate primary extension, domain-wise BH correction, 250/1,000 km scale checks with conditional 2,000-replicate extension, contract-specified point-direction checks, top-1% area checks, NEX polygon-only checks, and final support classification. Every bootstrap checkpoint carries the seed, scale, target count, method, occupied-block count, and sample digest; a mismatch forces a clean task rerun. NEX model-spread uncertainty remains separate and is never folded into the spatial bootstrap.

## Interpretation gates

- The analysis is a comparison of oases in BWh and BWk climate backgrounds at fixed 2020 boundaries.
- NEX fields concern future background `tasmax`, `tasmin`, and precipitation exposure only.
- FuturePop results are descriptive and coverage-aware.
- ET0 fields preserve raw polygon summaries under a unit-caution rule. They are outside the 21 estimands and 29 facts.
- The minimum table is not a substitute for excluded boundary geometry or original third-party products.
