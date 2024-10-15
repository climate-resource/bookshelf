# Changelog

Versions follow [Semantic Versioning](https://semver.org/) (`<major>.<minor>.<patch>`).

Backward incompatible (breaking) changes will only be introduced in major versions
with advance notice in the **Deprecations** section of releases.


<!--
You should *NOT* be adding new changelog entries to this file, this
file is managed by towncrier. See changelog/README.md.

You *may* edit previous changelogs to fix problems like typo corrections or such.
To add a new changelog entry, please see
https://pip.pypa.io/en/latest/development/contributing/#news-entries,
noting that we use the `changelog` directory instead of news, md instead
of rst and use slightly different categories.
-->

<!-- towncrier release notes start -->

## bookshelf v0.3.1b4 (2024-10-15)

### Features

- Deploy documentation automatically via the CI ([#109](https://github.com/climate-resource/bookshelf/pull/109))

### Improvements

- Replaced deprecated dependency `appdirs` with `platformdirs` ([#108](https://github.com/climate-resource/bookshelf/pull/108))
- Pin bookshelf version for producer ([#110](https://github.com/climate-resource/bookshelf/pull/110))

### Trivial/Internal Changes

- [#107](https://github.com/climate-resource/bookshelf/pull/107)


## bookshelf v0.3.1b3 (2024-10-13)

No significant changes.


## bookshelf v0.3.1b2 (2024-10-13)

No significant changes.


## bookshelf v0.3.1b1 (2024-10-13)

### Breaking Changes

- The `bookshelf` package has been split into two:
  * `bookshelf` - the core package for consuming content from the bookshelf
  * `bookshelf-producer` - the CLI tool for creating and managing books

  This should require no changes for data consumers.
  This change makes for a cleaner separation between consuming
  and producing datasets.

  ([#65](https://github.com/climate-resource/bookshelf/issue/65))

### Features

- Added Climate Resource's NDCs dataset to the bookshelf ([#56](https://github.com/climate-resource/bookshelf/issue/56))
- Add a functions to add long format data and compressed files ([#58](https://github.com/climate-resource/bookshelf/issue/58))
- Add a functions to get long format data from the book ([#59](https://github.com/climate-resource/bookshelf/issue/59))
- Added 20240318 version of CAT dataset to the bookshelf ([#64](https://github.com/climate-resource/bookshelf/issue/64))

### Improvements

- When running a notebook, the files were verified through data content hash code rather than file name hash code ([#60](https://github.com/climate-resource/bookshelf/issue/60))
- Migrate to github ([#106](https://github.com/climate-resource/bookshelf/pull/106))

### Bug Fixes

- resolve the issue where the upload and download files have rows in a different order. ([#63](https://github.com/climate-resource/bookshelf/issue/63))

### Improved Documentation

- Add example notebooks to docs ([#61](https://github.com/climate-resource/bookshelf/issue/61))
- Migrated documentation to use [mkdocs](https://www.mkdocs.org/).
  This allows us to write documentation in only MarkDown,
  instead of mixing reStructuredText and Markdown. ([#66](https://github.com/climate-resource/bookshelf/issue/66))

### Trivial/Internal Changes

- [#65](https://github.com/climate-resource/bookshelf/pull/65)


## bookshelf v0.3.0 (2024-01-31)


### Features

- * Added legacy GDP results from Excel NDC Tool. ([#42](https://github.com/climate-resource/bookshelf/bookshelf/issue/42))
- Add an updated version of the World Bank's World Development Indicators (v23). The `wdi` book has also been
  updated to edition 2. ([#43](https://github.com/climate-resource/bookshelf/bookshelf/issue/43))
- * Added greenhouse gas emissions data from Climate Action Tracker (CAT).
  * Added historical greenhouse gas emission data and projection data from PBL Netherlands Environmental Assessment Agency.
  * Added estimated energy sector CO2 emissions data from International Energy Agency.

  ([#45](https://github.com/climate-resource/bookshelf/bookshelf/issue/45))
- Add a function to display the structure of a dataset ([#48](https://github.com/climate-resource/bookshelf/bookshelf/issue/48))
- Add data dictionary to schema ([#49](https://github.com/climate-resource/bookshelf/bookshelf/issue/49))
- Add data dictionary verification ([#50](https://github.com/climate-resource/bookshelf/bookshelf/issue/50))
- Added NGFS3 emissions data. ([#53](https://github.com/climate-resource/bookshelf/bookshelf/issue/53))

### Bug Fixes

- Fix to the schema for datasets to allow no files to be specified ([#47](https://github.com/climate-resource/bookshelf/bookshelf/issue/47))
- Re-add notebook tests to CI

  Updated primap-hist and primap-ssp-downscaled editions to update reflect the renaming of `turkey` to `Türkiye` ([#51](https://github.com/climate-resource/bookshelf/bookshelf/issue/51))

### Trivial/Internal Changes

- [#55](https://github.com/climate-resource/bookshelf/bookshelf/issue/55)


## bookshelf v0.2.4 (2023-08-14)


### Features

- Added the Biennial Reports Common Table Format data reported by Annex-I parties as un-br-ctf.

  For now, contains the GHG projections data. ([#38](https://github.com/climate-resource/bookshelf/bookshelf/issue/38))

### Bug Fixes

- Add CLI entrypoint that was inadvertently missed when migrating to the new copier template. ([#39](https://github.com/climate-resource/bookshelf/bookshelf/issue/39))
- Fixed the un-br-ctf dataset, now includes a lot more data.

  Version 2023-08, edition 1 of the un-br-ctf dataset is to be considered broken, always
  use edition 2 instead. ([#40](https://github.com/climate-resource/bookshelf/bookshelf/issue/40))

### Improved Documentation

- Added documentation about generating and using new versions of Books locally. ([#41](https://github.com/climate-resource/bookshelf/bookshelf/issue/41))


## bookshelf v0.2.3 (2023-07-28)


### Features

- Add PRIMAP downscaled SSPs dataset: `primap-ssp-downscaled` ([#34](https://github.com/climate-resource/bookshelf/bookshelf/issue/34))
- Migrate to the common Climate Resource copier template

  Major changes include adding support for the use of `towncrier` for managing the changelogs and `liccheck` for verifying
  the compliance of any project dependencies. ([#35](https://github.com/climate-resource/bookshelf/bookshelf/issue/35))

### Improvements

- Use original region abbreviations in PRIMAP-hist. Bumps `primap-hist` to edition 4. ([#34](https://github.com/climate-resource/bookshelf/bookshelf/issue/34))
- Extract SSP marker scenarios in addition to the existing baseline scenarios. Bumps `primap-ssp-downscaled` to ed.2 ([#36](https://github.com/climate-resource/bookshelf/bookshelf/issue/36))

### Bug Fixes

- Convert PRIMAP-hist to units of the form `kt X / yr` to be consistent. Bumps `primap-hist` to ed.3 ([#32](https://github.com/climate-resource/bookshelf/bookshelf/issue/32))


## v0.2.2

### Added

- ([!27](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/27)) Add sphinx-based documentation
- ([!26](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/26)) Add `force` option to the publish CLI command to upload data even if a matching edition already exists
- ([!25](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/25)) Add primap-hist v2.4.1 and v2.4.2

### Changed

- ([!29](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/29)) Move `python-dotenv` from a development dependency to a core dependency
- ([!23](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/23)) Fix CEDs unit names for all resources. Bumps `ceds` to ed.3

### Fixed

- ([!28](https://github.com/climate-resource/bookshelf/bookshelf/issue/28)) Fix file retrieval and publishing on windows

## v0.2.1

### Changed

- ([!20](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/20)) Updated `DATA_FORMAT_VERSION` to `v0.2.1` in order to handle extra field
- ([!19](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/19)) Added gwp_context field to primap-hist for easier post processing
- ([!19](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/19)) Fixed the uploading of new editions

### Added

- ([!20](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/20)) Added the option to mark a version as "private". This version will not be listed, but can still be loaded if the version is specified.

## v0.2.0

### Changed

- ([!14](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/14)) Add sectoral information to CEDS and also support the initial CEDs release as part of Hoesly et al. 2018
- ([!17](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/17)) Added the concept of editions. Each time the processing changes the edition counter is incremented. The version identifier is reserved for the data source. This results in a breaking change of the data format which has been updated to `v0.2.0`.
- ([!16](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/16))  Updated `un-wpp@0.1.2` with some fixes to variable naming

## v0.1.0

### Changed

- ([!12](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/12)) Update primap-HIST to v0.2.0 to provide resources by region and by country
- ([!11](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/11)) Remove non-required dependencies from the  requirements
- ([!10](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/10)) Update issue and MR templates
- ([!7](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/7)) Renamed `LocalBook.metadata` to `LocalBook.as_datapackage`
- ([!6](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/6)) Renamed `Bookshelf.save` to `Bookshelf.publish`

### Added

- ([!15](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/15)) Add `un-wpp@v0.1.0`
- ([!13](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/13)) Add `ceds@0.0.1`
- ([!9](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/9)) Add `wdi@v0.1.1`
- ([!8](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/8)) Add `primap-hist@v0.1.0`
- ([!7](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/7)) Add `Bookshelf.list_versions`
- ([!6](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/6)) Add save CLI command
- ([!5](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/5)) Add CLI tool, `bookshelf` and CI test suite for notebooks
- ([!4](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/4)) Add NotebookMetadata schema and an example notebook with documentation
- ([!3](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/3)) Add ability to upload Books to a remote bookshelf
- ([!2](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/2)) Add precommit hooks and test coverage to the CI
- ([!1](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/1)) Add bandit and mypy to the CI
- Initial project setup
