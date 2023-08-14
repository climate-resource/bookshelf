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

## bookshelf v0.2.4 (2023-08-14)


### Features

- Added the Biennial Reports Common Table Format data reported by Annex-I parties as un-br-ctf.

  For now, contains the GHG projections data. ([#38](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/38))

### Bug Fixes

- Add CLI entrypoint that was inadvertently missed when migrating to the new copier template. ([#39](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/39))
- Fixed the un-br-ctf dataset, now includes a lot more data.

  Version 2023-08, edition 1 of the un-br-ctf dataset is to be considered broken, always
  use edition 2 instead. ([#40](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/40))

### Improved Documentation

- Added documentation about generating and using new versions of Books locally. ([#41](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/41))


## bookshelf v0.2.3 (2023-07-28)


### Features

- Add PRIMAP downscaled SSPs dataset: `primap-ssp-downscaled` ([#34](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/34))
- Migrate to the common Climate Resource copier template

  Major changes include adding support for the use of `towncrier` for managing the changelogs and `liccheck` for verifying
  the compliance of any project dependencies. ([#35](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/35))

### Improvements

- Use original region abbreviations in PRIMAP-hist. Bumps `primap-hist` to edition 4. ([#34](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/34))
- Extract SSP marker scenarios in addition to the existing baseline scenarios. Bumps `primap-ssp-downscaled` to ed.2 ([#36](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/36))

### Bug Fixes

- Convert PRIMAP-hist to units of the form `kt X / yr` to be consistent. Bumps `primap-hist` to ed.3 ([#32](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/32))


## v0.2.2

### Added

- ([!27](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/27)) Add sphinx-based documentation
- ([!26](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/26)) Add `force` option to the publish CLI command to upload data even if a matching edition already exists
- ([!25](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/25)) Add primap-hist v2.4.1 and v2.4.2

### Changed

- ([!29](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/29)) Move `python-dotenv` from a development dependency to a core dependency
- ([!23](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/23)) Fix CEDs unit names for all resources. Bumps `ceds` to ed.3

### Fixed

- ([!28](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/merge_requests/28)) Fix file retrieval and publishing on windows

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
