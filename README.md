# Global oasis exposure analysis

This repository contains the code and minimum author-created derived data needed to verify the principal numerical results of a fixed-boundary global oasis exposure assessment. The study population comprises 3,443 oasis polygons delineated for 2020. Boundary geometries and third-party source rasters are not redistributed.

## Release status

The public repository is complete and independently checkable. A versioned GitHub release and Zenodo DOI are intentionally pending author-approved creator names, order, ORCID identifiers, and affiliations. No DOI has been minted from provisional or guessed creator metadata.

The collective entity in `CITATION.cff` identifies the project only; it is not a substitute for the author-approved Zenodo creator list.

## Contents

- `data/analysis_input_minimal.csv`: 3,443 rows and only the fields required for the locked estimands, spatial-block checks, selected sensitivities, descriptive FuturePop facts, and the author-approved ET0 retention rule.
- `data/primary_estimands_21.csv`: the 21 locked primary estimates, confidence intervals, false-discovery-rate results, and support classifications.
- `data/master_numeric_facts_29.csv`: the 29 accepted numerical facts used by the reporting package.
- `data/Source_Data_CEE_v1.xlsx`: the Communications Earth & Environment Source Data workbook.
- `config/estimands.csv`: the machine-readable estimand contract.
- `src/` and `scripts/reproduce.py`: point-estimation, spatial-block bootstrap, multiplicity, sensitivity, and validation code.
- `data/data_dictionary.csv` and `data/source_product_manifest.csv`: field definitions and source-product lineage.
- `SHA256SUMS.txt`: SHA-256 checksums for the public package.

## Reproduce and verify

Create the pinned environment and run the default verifier:

```bash
conda env create -f environment.yml
conda activate global-oasis-exposure
python scripts/reproduce.py --resume
```

The default command recomputes all 21 point estimates from the minimum input table, integrity-checks the authoritative locked 500 km inference outputs and 250/1,000 km sensitivity records by SHA-256 and row-level contracts, reproduces the 16 robust / 2 sensitive / 3 not-supported classification rule from those locked records, checks all 29 facts, reads the Source Data workbook, and writes resumable state and logs outside the repository. It does **not** independently recompute the locked bootstrap confidence intervals, p-values, or FDR q-values. See `docs/reproduction_workflow.md` for details.

An opt-in full orchestration is also provided:

```bash
python scripts/reproduce.py --resume --full-bootstrap
```

This executes the pre-specified 21 primary 500 km tasks with 2,000 effective replicates, conditional primary extension, domain-wise BH correction, 250/1,000 km sensitivity tasks with conditional extension, registered aggregation/weighting checks, top-1% area checks, and NEX polygon-only checks. It writes checkpoints, task state, logs, and outputs under the selected output directory. It is intentionally not invoked during release construction because this release preserves rather than replaces the approved locked inference.

Expected terminal status:

```text
PASS: 21/21 estimands; 16 robust, 2 sensitive, 3 not_supported; 29/29 facts
```

## Scope and interpretation

- `BWh oases` and `BWk oases` mean oases in hot-desert and cold-desert climate backgrounds, respectively. The analysis does not infer oasis-interior microclimate or causality.
- NEX-GDDP-CMIP6 fields describe future **background climate exposure** at fixed 2020 oasis boundaries. They are not future oasis extent, UTCI, surface water, groundwater, or water resources.
- FuturePop fields are coverage-aware descriptive scenario totals, not inferential estimates or a continuation of observed GHSL data.
- ET0 polygon summaries are retained exactly under the author-approved raw/unit-caution rule. They do not enter the 21 estimands or 29 facts and must not be interpreted as final-unit ET0, water use, or water resources.

## Excluded material

This repository does not contain oasis shapefiles, source rasters or NetCDF files, downloaded archives, manuscript or supplementary files, figures, submission packages, project history, internal QA/logs, credentials, or local absolute paths. See `THIRD_PARTY_NOTICES.md` for source-product notices.

## Licences

- Code in `src/`, `scripts/`, and `tests/`: MIT (`LICENSE`).
- Author-created derived data, configuration, and documentation: CC BY 4.0 (`LICENSE-DATA`).
- Third-party raw data: not redistributed and remain subject to their providers' terms.

Until a version DOI is issued, cite the exact Git commit used. The future version DOI will be the citation target for a released snapshot; the future concept DOI will identify the evolving repository.
