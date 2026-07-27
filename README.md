# Global oasis exposure: 3,437-oasis analysis data release

This repository contains the minimum author-created derived data and non-graphical analysis modules for the current 3,437-oasis analysis population.

## Included

- 3,437-row minimum analysis input with six excluded identifiers absent
- 31 primary estimand records and their analysis definitions
- Core non-graphical inference modules, a pinned Python environment, and a structural verification test
- The Source Data workbook underlying the manuscript figures and tables, and the script that builds it
- Public product-version, citation, and redistribution-boundary metadata
- Third-party data notices

## Where to start

| Path | What it is |
|---|---|
| `docs/reproduction_workflow.md` | What this release can and cannot reproduce, and how |
| `scripts/reproduce.py` | The verifier entry point; recomputes all 31 point estimands and writes a receipt |
| `tests/verify_current_minimum.py` | Fast structural check plus a full 31/31 recomputation |
| `data/analysis_input_minimal.csv` | The 3,437-row analysis table |
| `data/primary_estimands_31.csv` | The 31 locked primary estimates, intervals, q-values and support classes |
| `config/estimands_31.csv` | The estimand contract each result is computed from |
| `data/Source_Data_CEE_v1.xlsx` | Source Data for the manuscript figures and tables |

```
python scripts/reproduce.py
```

`code/` cannot be imported as a package, because the Python standard library
ships a module of the same name. Run the verifier through `scripts/reproduce.py`,
which puts the directory on the path itself.

## Not included

No oasis boundary geometries, third-party rasters, NetCDF files, downloaded archives, rendered figure exports, figure-plotting code, Word/PDF construction code, manuscripts, supplementary manuscripts, credentials, or local filesystem paths are included.

## Reproduction boundary

The supplied derived records are versioned release inputs. The verification test checks row identity, keyset conservation, and the 31 primary estimand records, and recomputes every one of the 31 point estimates from the shipped table. It does not download restricted source products or regenerate raster overlays, and it does not re-draw the cluster bootstrap on the default path: 95% intervals and FDR q-values are checked against the locked ledger rather than independently re-derived. See `docs/reproduction_workflow.md` for the full boundary.

## Identifier rule

OasisID values in this public release belong to the current 3,437-oasis analysis population.

## Release scope

This release contains derived summaries and verification code only; provider-controlled source products and boundary geometries remain excluded.

## Archive

The versioned release archive is preserved by Zenodo. Use the concept DOI to resolve the latest version: <https://doi.org/10.5281/zenodo.21304984>.
