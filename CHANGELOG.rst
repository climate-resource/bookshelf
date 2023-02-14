Changelog
=========

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.0.0/>`_, and this project adheres to `Semantic Versioning <https://semver.org/spec/v2.0.0.html>`_.

The changes listed in this file are categorised as follows:

    - Added: new features
    - Changed: changes in existing functionality
    - Deprecated: soon-to-be removed features
    - Removed: now removed features
    - Fixed: any bug fixes
    - Security: in case of vulnerabilities.

Unreleased
----------

v0.2.1
------


Changed
=======

- (`!21 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/21>`_) Replace NO2 with NOx in CEDs units
- (`!20 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/20>`_) Updated ``DATA_FORMAT_VERSION`` to ``v0.2.1`` in order to handle extra field
- (`!19 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/19>`_) Added gwp_context field to primap-hist for easier post processing
- (`!19 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/19>`_) Fixed the uploading of new editions


Added
=====

- (`!20 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/20>`_) Added the option to mark a version as "private". This version will not be listed, but can still be loaded if the version is specified.

v0.2.0
------

Changed
=======
- (`!14 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/14>`_) Add sectoral information to CEDS and also support the initial CEDs release as part of Hoesly et al. 2018
- (`!17 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/17>`_) Added the concept of editions. Each time the processing changes the edition counter is incremented. The version identifier is reserved for the data source. This results in a breaking change of the data format which has been updated to ``v0.2.0``.
- (`!16 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/16>`_)  Updated ``un-wpp@0.1.2`` with some fixes to variable naming


v0.1.0
------

Changed
=======
- (`!12 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/12>`_) Update primap-HIST to v0.2.0 to provide resources by region and by country
- (`!11 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/11>`_) Remove non-required dependencies from the  requirements
- (`!10 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/10>`_) Update issue and MR templates
- (`!7 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/7>`_) Renamed ``LocalBook.metadata`` to ``LocalBook.as_datapackage``
- (`!6 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/6>`_) Renamed ``Bookshelf.save`` to ``Bookshelf.publish``

Added
=====
- (`!15 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/15>`_) Add ``un-wpp@v0.1.0``
- (`!13 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/13>`_) Add ``ceds@0.0.1``
- (`!9 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/9>`_) Add ``wdi@v0.1.1``
- (`!8 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/8>`_) Add ``primap-hist@v0.1.0``
- (`!7 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/7>`_) Add ``Bookshelf.list_versions``
- (`!6 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/6>`_) Add save CLI command
- (`!5 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/5>`_) Add CLI tool, ``bookshelf`` and CI test suite for notebooks
- (`!4 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/4>`_) Add NotebookMetadata schema and an example notebook with documentation
- (`!3 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/3>`_) Add ability to upload Books to a remote bookshelf
- (`!2 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/2>`_) Add precommit hooks and test coverage to the CI
- (`!1 <https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/1>`_) Add bandit and mypy to the CI
- Initial project setup
