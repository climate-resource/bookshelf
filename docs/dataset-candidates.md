# Dataset ingestion candidates

A long list of datasets worth ingesting into the Bookshelf, focused on data that is
useful as **comparison points against our own products** (PRIMAP-hist, NDC pipelines,
MAGICC-related scenario work, and the existing books: `rcmip-emissions`, `ceds`, `iea`,
`hadcrut`, `un-wpp`, `wb-population`, `wdi`, `imf-weo`, `ssp-basic-elements`,
`ndcs-pbl`, `un-br-ctf`, `primap-ssp-downscaled`, `gdp-ndc-tool`).

Compiled 2026-09-01 via web research (Exa). Licences were checked from the source
pages where possible but should be re-verified at ingestion time — several sources
have changed licence between releases (notably PRIMAP-hist v2.7 and IEA-linked data).

Legend for the **Republishable** column:

- ✅ open licence permitting redistribution (CC BY 4.0, CC0, public domain, or similar)
- ⚠️ restricted (non-commercial, share-alike, no-redistribution, or bespoke terms) —
  may still be ingestible for internal comparison, or under a commercial licence
- 🔍 scrape target — data lives in a portal/API without clean versioned bulk files;
  we would build a notebook that scrapes/queries and snapshots it

---

## 1. National & global GHG emissions inventories

These are the most direct comparison points for PRIMAP-hist and CEDS.

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **EDGAR Community GHG database** (JRC/IEA) | Independent country × sector × gas emissions 1970–2024, annual + monthly, also gridded. The canonical "third-party" comparator. | Bulk xlsx/nc from edgar.jrc.ec.europa.eu | ✅ CC BY 4.0, *except* the IEA-EDGAR CO2 component which is CC BY-NC-ND 4.0 — split the book or flag the CO2 energy component |
| **Global Carbon Project fossil CO2 (GCB / Andrew & Peters)** | Fossil CO2 by country/fuel 1750–2024, absolute + per-capita, annual releases on Zenodo (e.g. 10.5281/zenodo.17417124). | Zenodo CSV | ✅ CC BY 4.0 |
| **Global Carbon Budget full dataset** | Global budget: fossil, land-use change, ocean/land sinks, atmospheric growth. | globalcarbonbudget.org xlsx + ICOS | ✅ CC BY 4.0 |
| **UNFCCC Annex I CRT/CRF inventories** | Country-reported official inventories (the ground truth PRIMAP-hist ingests). | Per-party zip files on unfccc.int; DI portal (di.unfccc.int) has an API-ish interface | ✅ public data; 🔍 scrape target — submissions pages + DI flexible-query interface |
| **UNFCCC non-Annex I / BTR submissions** | BTR CRT tables, BURs, NCs for developing countries. | unfccc.int submission pages (mixed xlsx/pdf) | ✅ public; 🔍 scrape target, messy formats |
| **Climate Watch historical GHG emissions** (WRI) | Harmonised country GHG (CAIT), multi-source, with bulk downloads and a documented REST API. | Bulk CSV + api/v1/data/historical_emissions | ✅ CC BY 4.0 (Climate Watch data); some embedded third-party series carry their own terms |
| **Climate TRACE emissions inventory** | Satellite/ML-derived independent inventory: country totals from 2015, monthly asset-level from 2021, >2.7M sources; monthly releases, archived on Zenodo. | climatetrace.org/data CSV packages, API, BigQuery | ✅ CC BY 4.0 |
| **FAOSTAT emissions domains (GT/EM etc.)** | Agriculture, land-use and agrifood-system emissions by country, 1961→; also the AFOLU comparator used inside PRIMAP-hist. | Bulk zip CSV via bulks-faostat.fao.org (no auth) | ⚠️ CC BY-NC-SA 3.0 IGO — check FAO open-data terms per domain |
| **GFED (Global Fire Emissions Database)** | Fire/biomass-burning emissions, gridded + regional. | globalfiredata.org / archive | ✅ CC BY 4.0 (GFED4/5) |
| **CEDS releases (newer versions)** | We already carry CEDS; ingest new versioned releases from the ESGF/Zenodo archives to track their revisions. | Zenodo / GitHub | ✅ CC BY 4.0 |
| **National inventories not in UNFCCC flows** (e.g. Taiwan EPA, S. Korea GIR pre-submission, US EPA GHGI standalone) | Fills gaps and gives earlier-than-UNFCCC comparison points. | Agency websites | 🔍 scrape targets, per-country terms (US EPA is public domain ✅) |

## 2. NDCs, targets & policy trackers

Comparators for the NDC quantification work (`ndcs-pbl`, `gdp-ndc-tool`).

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **Climate Watch NDC tracker + NDC content** | Structured NDC indicators (150+), NDC tracker status, pledges, LTS content, NDC full text. | Bulk CSV downloads + API | ✅ CC BY 4.0 |
| **Climate Action Tracker (CAT) data explorer** | Historical emissions, current-policy projections, target emissions, fair-share and modelled domestic pathways for ~40 countries. | Download from cat-data-explorer | ⚠️ CC BY-NC-SA-ish terms; verify. 🔍 partial scrape target (per-country JSON behind explorer) |
| **PBL Climate Pledge NDC tool** | We ingest a version already (`ndcs-pbl`); new releases + the Zenodo "Infographics PBL NDC tool" data are the refresh path. | themasites.pbl.nl + Zenodo | ✅ Zenodo data CC BY; keep updated |
| **Net Zero Tracker** (ECIU/Oxford) | Net-zero targets of countries, regions, cities, companies with status metadata. | zerotracker.net bulk xlsx/API | ✅ CC BY 4.0 |
| **IEA Climate Pledges Explorer** | IEA's estimate of energy-sector GHG implied by each NDC/net-zero pledge. | Explorer download | ⚠️ IEA terms (CC BY-NC-SA); explorer = 🔍 scrape target |
| **UNFCCC NDC registry** | The authoritative NDC PDFs + submission dates. | unfccc.int NDC registry | ✅ public documents; 🔍 scrape target for metadata (submission dates, versions) |
| **Climate Policy Database** (NewClimate Institute) | National mitigation policies inventory. | climatepolicydatabase.org CSV export | ✅ CC BY 4.0 |
| **ICAP ETS map / World Bank Carbon Pricing Dashboard** | Carbon pricing instruments, coverage and prices. | Downloads / dashboard | ⚠️ mixed; WB dashboard CC BY 4.0 ✅; ICAP = 🔍 scrape target |

## 3. Scenarios & pathways

Comparators for RCMIP, SSP and MAGICC-adjacent products.

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **IPCC AR6 Scenarios Database (IIASA)** | 3,131 scenarios incl. climate diagnostics (MAGICC/FaIR/CICERO-SCM) — direct comparator for our scenario/climate-assessment outputs. | data.ece.iiasa.ac.at/ar6 (login-gated CSV) | ⚠️ licence permits research/science-communication use but **restricts redistribution of substantial parts** — likely internal-only book or per-figure extracts; 🔍 login-gated download |
| **SR1.5 / AR5 scenario databases (IIASA)** | Older ensembles, still used as reference lines. | IIASA scenario explorers | ⚠️ same restriction pattern |
| **ENGAGE / NGFS scenario databases** | Policy-relevant scenario ensembles (NGFS via IIASA explorer, semi-annual vintages). | IIASA explorers, NGFS downloads | ⚠️ NGFS phase data mostly open (check per phase); explorer = 🔍 |
| **SSP database update (SSP 2023/2024 release, IIASA)** | Updated SSP basic drivers (population, GDP) — refresh path for `ssp-basic-elements`. | IIASA SSP explorer | ⚠️ check release-specific licence; 🔍 login-gated |
| **RCMIP / CMIP7 harmonised emissions (input4MIPs)** | Successor pipelines to `rcmip-emissions` (CR is involved); CMIP7 scenario emissions from input4MIPs/ESGF. | ESGF, Zenodo | ✅ CC BY 4.0 typically |
| **AR6 historical emissions + infilling database** | The harmonisation/infilling reference sets used by climate-assessment (Zenodo 10.5281/zenodo.6390768). | Zenodo | ✅ CC BY |

## 4. Observed climate — temperature & indicators

Comparators for `hadcrut` and for "are we on track" analyses.

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **NASA GISTEMP v4** | Global/hemispheric/zonal monthly anomalies 1880→, CSV + gridded nc/zarr. | data.giss.nasa.gov, stable URLs | ✅ US public domain |
| **NOAAGlobalTemp v6** | Global anomalies + 5° grids; note versioned file names change monthly (URL churn). | NCEI ASCII/netCDF | ✅ public domain; mild 🔍 (URL discovery) |
| **Berkeley Earth** | Land+ocean 1850→, new high-res 0.25° product. | berkeleyearth.org / S3 / GCS text files | ⚠️ CC BY-NC 4.0 — non-commercial only |
| **ERA5 / ERA5 monthly 2m temperature** (Copernicus) | Reanalysis global means, 1940→. | CDS API (key required) | ✅ Copernicus licence allows redistribution with attribution; 🔍 API-based retrieval |
| **HadCRUT5 ensemble** (already ingested) | Keep ingesting new versions; also CRUTEM5 and HadSST4 components. | Met Office hadobs | ✅ Open Government Licence |
| **Indicators of Global Climate Change (IGCC / ClimateIndicator)** | Annually updated AR6-style indicators: attributed warming, ERF, EEI, GMST, concentrations, remaining carbon budget, sea level. Excellent one-stop comparator. | GitHub + Zenodo (10.5281/zenodo.21494229 for 2025) | ✅ CC BY 4.0 |
| **HadEX3 / GHCN extremes** | Temperature/precip extremes indices. | Met Office / NOAA | ✅ mostly open; check HadEX terms |

## 5. Atmospheric concentrations & forcing

Comparators for MAGICC concentration outputs.

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **NOAA GML global trends (CO2, CH4, N2O, SF6)** | Global/monthly marine-boundary-layer means, flat txt/CSV at stable URLs. | gml.noaa.gov/ccgg/trends | ✅ public domain w/ citation request |
| **WMO WDCGG global means** | Alternative global means (includes inland stations; ~0.4 ppm higher CO2 than NOAA). | gaw.kishou.go.jp CSV | ✅ open with citation; verify terms |
| **AGAGE** | Multi-species (incl. F-gases, ODSs) station + global data. | agage.mit.edu / CDIAC-ESS archives | ✅ open with citation/coauthorship etiquette |
| **Meinshausen et al. CMIP6/CMIP7 historical GHG concentrations** | The concentration forcing datasets CR co-authors; versioned comparator for concentration projections. | input4MIPs/ESGF, Zenodo | ✅ CC BY 4.0 |
| **NOAA Annual Greenhouse Gas Index (AGGI)** | Radiative forcing by gas, annually. | gml.noaa.gov table | ✅ public domain; mild 🔍 (HTML table) |

## 6. Energy & activity data

Comparators for `iea` and drivers for emissions models.

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **Ember yearly + monthly electricity data** | Generation, capacity, demand, power-sector emissions for 215 geographies, 2000→, updated twice monthly; CSV + API. | ember-energy.org | ✅ CC BY 4.0 |
| **Energy Institute Statistical Review of World Energy** | Successor to BP StatsReview; primary energy, fossil production/consumption 1965→ (a PRIMAP-hist input). | xlsx/CSV download | ⚠️ free to use with attribution but check redistribution clause |
| **Our World in Data energy dataset (owid/energy-data)** | Tidy compilation of EI + Ember + SHIFT, one CSV, versioned on GitHub. | GitHub CSV/JSON | ✅ CC BY 4.0 (OWID layer); underlying sources retain their terms |
| **IRENA renewable capacity & generation statistics** | Renewable capacity by country/tech. | IRENASTAT / xlsx | ⚠️ free w/ attribution, redistribution restrictions; 🔍 PxWeb portal |
| **EIA international energy data** | US EIA's international energy statistics + open API. | api.eia.gov (key, free) | ✅ US public domain; 🔍 API-based |
| **JODI oil & gas** | Monthly oil/gas production/consumption. | jodidata.org CSV | ✅ open use; verify redistribution |
| **Global Energy Monitor trackers** (coal plants, gas, steel, etc.) | Asset-level infrastructure trackers. | xlsx downloads on registration | ⚠️ CC BY-NC where stated; some trackers CC BY ✅ — check per tracker |

## 7. Socioeconomics (population, GDP)

Comparators/refresh paths for `un-wpp`, `wb-population`, `wdi`, `imf-weo`.

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **UN WPP revisions (2024→)** | Keep versioned ingests of each revision; the comparison across revisions is itself valuable. | population.un.org CSV/xlsx | ✅ CC BY 3.0 IGO |
| **World Bank WDI / population** (already ingested) | Refresh via API; versioned snapshots. | api.worldbank.org | ✅ CC BY 4.0 |
| **IMF WEO** (already ingested) | New vintages 2×/year; vintage-to-vintage GDP revisions matter for NDC BAU baselines. | imf.org xlsx/SDMX | ✅ free use w/ attribution |
| **Maddison Project Database** | Long-run GDP/capita 1 CE→, for historical context. | rug.nl xlsx | ✅ open academic use |
| **Penn World Table** | PPP national accounts comparator. | rug.nl / FRED | ✅ CC BY 4.0 |
| **OECD Economic Outlook / national accounts** | GDP projections comparator for WEO. | OECD.Stat / SDMX API | ✅ most OECD data now CC BY 4.0; 🔍 SDMX |
| **UN SNA / UNSD national accounts** | Official GDP levels. | unstats API | ✅ open; 🔍 API |

## 8. Land use, forests & other

| Dataset | What it is | Access | Republishable |
| --- | --- | --- | --- |
| **Global Forest Watch / Hansen tree-cover loss** | Forest loss, country aggregates. | GFW downloads/API | ✅ CC BY 4.0 |
| **FAO FRA (Forest Resources Assessment)** | Country forest area/change. | fra-data.fao.org bulk | ⚠️ FAO terms (as FAOSTAT) |
| **HYDE** | Long-run land-use and population 10,000 BCE→. | Utrecht/PBL download | ✅ CC BY |
| **BLUE / H&C / OSCAR land-use CO2 (via GCB)** | LULUCF flux comparators packaged in the Global Carbon Budget. | GCB xlsx | ✅ CC BY 4.0 |
| **NOAA/NASA sea level (altimetry), PSMSL tide gauges** | SLR comparison for climate outputs. | Stable file URLs | ✅ open |
| **NSIDC sea ice index** | Arctic/Antarctic sea-ice extent. | NSIDC CSV | ✅ open |

---

## Suggested prioritisation

1. **High value, clean licences, trivial ingestion** (do first):
   GCP fossil CO2 (Zenodo), EDGAR (non-CO2 components), Climate Watch bulk data,
   Climate TRACE country-level, Ember yearly electricity, GISTEMP, NOAAGlobalTemp,
   NOAA GML trends, IGCC/ClimateIndicator, OWID energy, Net Zero Tracker.
2. **High value, already-adjacent** (refresh/versioned re-ingests):
   UN WPP 2024, IMF WEO vintages, PBL NDC tool updates, CEDS new releases,
   HadCRUT5 point releases.
3. **High value but licence-constrained** (internal comparison books, or commercial licence):
   AR6/SSP/NGFS scenario databases (IIASA), Berkeley Earth, IEA-EDGAR CO2, FAOSTAT,
   CAT data explorer, Energy Institute StatsReview.
4. **Scrape targets** (need notebook-level scrapers + snapshotting):
   UNFCCC DI portal and CRT/BTR submission pages, UNFCCC NDC registry metadata,
   CAT per-country explorer JSON, IEA Climate Pledges Explorer, IRENA PxWeb,
   ICAP ETS map, national inventory agencies (Taiwan, Korea GIR, US EPA GHGI).

Notes:

- For portal/API sources, the bookshelf pattern of versioned snapshot books works
  well: scrape → normalise → publish with the retrieval date in the version.
- Anything ⚠️ non-commercial needs a decision before *re*-publishing through a public
  bookshelf; ingestion for internal comparison is usually still fine, but the book
  metadata should carry the upstream licence so consumers can filter.
- PRIMAP-hist itself moved to CC BY-NC-SA at v2.7 — a useful reminder to record the
  licence per version, not per dataset.
