# Third-party data notices

No third-party raw raster, NetCDF, archive, or boundary-geometry file is redistributed in this repository. The public CSV and XLSX files contain author-created polygon summaries and metadata derived from the products below. Users who need source data must obtain them from the original providers and comply with the applicable terms.

| Product | Role in this repository | Source or citation |
|---|---|---|
| 2020 global oasis boundary lineage | Fixed population of 3,437 polygons; identifiers and derived summaries only; geometries excluded | [Dataset catalogue DOI](https://doi.org/10.3974/geodp.2025.03.01) |
| High-resolution Köppen-Geiger maps | Background BWh/BWk classification | [Beck et al.](https://doi.org/10.1038/s41597-023-02549-6) |
| GHS-POP and GHS-BUILT-S R2023A | 2020 population, density, built share, and population weights | [GHS-POP](https://doi.org/10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE); [GHS-BUILT-S](https://doi.org/10.2905/9F06F36F-4B11-47EC-ABB0-4F8B7B1D72EA) |
| Global Aridity Index and ET0 v3.1 | Scaled aridity-index estimate; ET0 retained as raw/unit-caution summaries only | [Zomer, Xu and Trabucco](https://doi.org/10.1038/s41597-022-01493-1) |
| TerraClimate | 1991–2020 background climatic water deficit | [Abatzoglou et al.](https://doi.org/10.1038/sdata.2017.191) |
| JRC Global Surface Water v1.4 | 1984–2021 historical/current ever-water fraction | [Pekel et al.](https://doi.org/10.1038/nature20584) |
| ERA5-HEAT UTCI | 1991–2020 background heat- and cold-stress days | [Di Napoli et al.](https://doi.org/10.1002/gdj3.102) |
| FuturePop v0.2 | Coverage-aware SSP2/SSP5 descriptive population scenarios | [WorldPop](https://doi.org/10.5258/SOTON/WP00849) |
| NEX-GDDP-CMIP6 | Future background tasmax, tasmin, and precipitation exposure | [Thrasher et al.](https://doi.org/10.1038/s41597-022-01393-4) |

The files `data/source_product_manifest_current.csv` and `data/third_party_product_boundary.csv` record the version or period, analysis role, provider/citation boundary, and redistribution status for each product. Nothing in the MIT or CC BY 4.0 licences grants rights in third-party source products.
