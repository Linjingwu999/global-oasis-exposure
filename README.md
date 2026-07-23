# Global oasis exposure: 3,437-oasis analysis release candidate

This repository contains the minimum author-created derived data and analysis modules for the current 3,437-oasis analysis population.

## Included

- 3,437-row minimum analysis input with six excluded identifiers absent
- 31 primary estimand records, 39 numeric facts, and the denominator contract
- Current Figure 1–8 source-data mappings and derived plot data for Figures 2–8
- Selected Figure 5 and Figure 6 exports with unit/threshold evidence sidecars
- The 117-row old/current identifier crosswalk and namespace guard
- Core inference modules, a pinned Python environment, and a structural verification test
- Checksums and third-party data notices

## Not included

No oasis boundary geometries, third-party rasters, NetCDF files, downloaded archives, figure-building code, table-building code, Word/PDF construction code, manuscripts, supplementary manuscripts, credentials, or local filesystem paths are included.

## Reproduction boundary

The supplied derived records are versioned release inputs. The verification test checks row identity, keyset conservation, estimand and fact counts, denominator presence, crosswalk completeness, and Figure 1–8 source-data mappings. It does not download restricted source products or regenerate raster overlays.

## Identifier rule

Stable old identifiers and re-encoded current identifiers are separate namespaces. Direct joins are prohibited; joins across namespaces require the complete 117-row crosswalk.

## Release scope

This release candidate supersedes the historical 3,443-oasis, 21-estimand, 29-fact package for the current analysis. It contains derived summaries and verification code only; provider-controlled source products and boundary geometries remain excluded.
