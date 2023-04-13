Releasing
=========


First step
----------

#. Update ``CHANGELOG.rst``:

    - add a header for the new version between ``master`` and the latest bullet point
    - this should leave the section underneath the master header empty

#. ``git checkout -b release-vX.Y.Z``
#. ``git add .``
#. ``git commit -m "chore(release): vX.Y.Z"``
#. ``git push``

Go to `Bookshelf's gitlab page <https://gitlab.com/climate-resource/bookshelf/bookshelf>`_ and create a MR request. You can merge it right away.

PyPI
----

To upload a release to PyPi run the following

#. ``git tag vX.Y.Z``
#. ``make build``
#. ``make deploy``
#. Go to `Bookshelf's PyPI`_ and check that the new release is as intended.


Finally push the new tag to remote

#. ``git push --tags``


.. _`Bookshelf's PyPI`: https://pypi.org/project/bookshelf/
