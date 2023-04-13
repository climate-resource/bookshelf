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
#. ``git tag vX.Y.Z``

PyPI
----

To upload a release to PyPi run the following

#. ``make build``
#. ``make deploy``
#. Go to `Bookshelf's PyPI`_ and check that the new release is as intended.


Push to repository
------------------

Finally, merge the release into master

#. ``git push``
#. ``git push --tags``

Go to `Bookshelf's gitlab page <https://gitlab.com/climate-resource/bookshelf/bookshelf>`_ and create a MR request. You can merge it right away.


.. _`Bookshelf's PyPI`: https://pypi.org/project/bookshelf/
