# Global oasis exposure: 3,437-oasis analysis data release

This repository contains the minimum author-created derived data and non-graphical analysis modules for the current 3,437-oasis analysis population.

## Included

- 3,437-row minimum analysis input with six excluded identifiers absent
- 31 primary estimand records, 39 numeric facts, and the denominator contract
- The 117-row old/current identifier crosswalk and namespace guard
- Core non-graphical inference modules, a pinned Python environment, and a structural verification test
- The 39-sheet Source Data workbook and its public product-version metadata
- Third-party data notices

## Not included

No oasis boundary geometries, third-party rasters, NetCDF files, downloaded archives, figure-building code, table-building code, Word/PDF construction code, manuscripts, supplementary manuscripts, credentials, or local filesystem paths are included.

## Reproduction boundary

The supplied derived records are versioned release inputs. The verification test checks row identity, keyset conservation, estimand and fact counts, denominator presence, crosswalk completeness, and the 39-sheet Source Data workbook. It does not download restricted source products or regenerate raster overlays.

## Identifier rule

Stable old identifiers and re-encoded current identifiers are separate namespaces. Direct joins are prohibited; joins across namespaces require the complete 117-row crosswalk.

## Release scope

This release contains derived summaries and verification code only; provider-controlled source products and boundary geometries remain excluded.
