# Global oasis exposure: 3,437-oasis analysis — v1.1.5

This repository contains the minimum author-created derived data and non-graphical analysis modules for the v1.1.5 3,437-oasis analysis population.

## Included

- 3,437-row minimum analysis input with six excluded identifiers absent
- 31 primary estimand records and their analysis definitions
- Core non-graphical inference modules, a pinned Python environment, and structural verification tests
- `Source_Data_CEE_v1_1_4.xlsx`, the 31-sheet Source Data workbook underlying the manuscript figures and tables
- Public product-version, citation, and redistribution-boundary metadata
- Third-party data notices

This release is aligned to 3,437 oases, 31 primary comparisons, a 30-model NEX ensemble, and the current FuturePop coverage accounting (3,181 oases valid for every scenario-year combination; 256 requiring nearest-valid-grid substitution in at least one combination). Figure 5 class summaries use oasis-area weighting for AI, ET0, ET0 SD and TerraClimate variables, with water fractions weighted by water-pixel area. Figure 6 primary threshold summaries use lower-order oasis-unit medians and IQRs at heat ≥32 °C and cold ≤−13 °C.

## Where to start

| Path | What it is |
|---|---|
| `docs/reproduction_workflow.md` | What this release can and cannot reproduce, and how |
| `scripts/reproduce.py` | The verifier entry point; recomputes all 31 point estimands and writes a receipt |
| `tests/verify_current_minimum.py` | Fast structural check plus a full 31/31 recomputation |
| `tests/verify_source_data_v1_1_4.py` | Source Data workbook sheet, count, weighting and threshold checks |
| `data/analysis_input_minimal.csv` | The 3,437-row analysis table |
| `data/primary_estimands_31.csv` | The 31 locked primary estimates, intervals, q-values and support classes |
| `config/estimands_31.csv` | The estimand contract each result is computed from |
| `data/Source_Data_CEE_v1_1_4.xlsx` | 31-sheet Source Data for the manuscript figures and tables |

```
python scripts/reproduce.py
```

`code/` cannot be imported as a package, because the Python standard library
ships a module of the same name. Run the verifier through `scripts/reproduce.py`,
which puts the directory on the path itself.

## Not included

No oasis boundary geometries, third-party rasters, NetCDF files, downloaded archives, rendered figure exports, figure-plotting or layout code, Word/PDF construction code, manuscripts, supplementary manuscripts, credentials, or local filesystem paths are included. The v1.1.4 workbook generator is kept outside this public repository; the workbook itself is the public Source Data artifact.

## Reproduction boundary

The supplied derived records are versioned release inputs. The verification test checks row identity, keyset conservation, and the 31 primary estimand records, and recomputes every one of the 31 point estimates from the shipped table. It does not download restricted source products or regenerate raster overlays, and it does not re-draw the cluster bootstrap on the default path: 95% intervals and FDR q-values are checked against the locked ledger rather than independently re-derived. See `docs/reproduction_workflow.md` for the full boundary.

## Identifier rule

OasisID values in this public release belong to the current 3,437-oasis analysis population.

## Release scope

This release contains derived summaries and verification code only; provider-controlled source products and boundary geometries remain excluded. The MIT code licence and existing CC BY 4.0 data licence are unchanged.

## Archive

The existing archive record is preserved by Zenodo. Use the concept DOI to resolve the archived versions: <https://doi.org/10.5281/zenodo.21304984>.
