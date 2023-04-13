Contributing
============

All contributions are welcome, some possible suggestions include:

- tutorials (or support questions which, once solved, result in a new tutorial :D)
- blog posts
- improving the documentation
- bug reports
- feature requests
- pull requests

Please report issues or discuss feature requests in the `Bookshelf issue tracker`_.
If your issue is a feature request or a bug, please use the templates available, otherwise, simply open a normal issue :)

As a contributor, please follow a couple of conventions:

- Create issues in the `Bookshelf issue tracker`_ for changes and enhancements, this ensures that everyone in the community has a chance to comment
- Be welcoming to newcomers and encourage diverse new contributors from all backgrounds: see the `Python Community Code of Conduct <https://www.python.org/psf/codeofconduct/>`_
- Only push to your own branches, this allows people to force push to their own branches as they need without fear or causing others headaches
- Start all pull requests as draft pull requests and only mark them as ready for review once they've been rebased onto master, this makes it much simpler for reviewers
- Try and make lots of small pull requests, this makes it easier for reviewers and faster for everyone as review time grows exponentially with the number of lines in a pull request


Getting setup
-------------

To get setup as a developer, we recommend the following steps (if any of these tools are unfamiliar, please see the resources we recommend in `Development tools`_):

#. Run ``make virtual-environment``, if that fails you can try doing it manually

    #. Change your current directory to the root directory (i.e. the one which contains ``README.rst``), ``cd ndc-quantification``
    #. Create a virtual environment to use ``python3 -m venv venv``
    #. Activate your virtual environment ``source ./venv/bin/activate``
    #. Upgrade pip ``pip install --upgrade pip wheel``
    #. Install the development dependencies (very important, make sure your virtual environment is active before doing this) ``pip install -e .[dev]``

#. Make sure the tests pass by running ``make test``, if that fails the commands are

    #. Activate your virtual environment ``source ./venv/bin/activate``
    #. Run the unit and integration tests ``pytest --cov -r a --cov-report term-missing``

Development tools
~~~~~~~~~~~~~~~~~

This list of development tools is what we rely on to develop the Bookshelf reliably and reproducibly.
It gives you a few starting points in case things do go inexplicably wrong and you want to work out why.
We include links with each of these tools to starting points that we think are useful, in case you want to learn more.

- `Git <http://swcarpentry.github.io/git-novice/>`_

- `Make <https://swcarpentry.github.io/make-novice/>`_

- `Pip and pip virtual environments <https://www.dabapps.com/blog/introduction-to-pip-and-virtualenv-python/>`_

- `Tests <https://semaphoreci.com/community/tutorials/testing-python-applications-with-pytest>`_

    - we use a blend of `pytest <https://docs.pytest.org/en/latest/>`_ and the inbuilt Python testing capabilities for our tests so checkout what we've already done in ``tests`` to get a feel for how it works

- `Continuous integration (CI) <https://docs.gitlab.com/ee/ci/introduction/index.html#continuous-integration>`_

    - we use `Gitlab CI <https://docs.gitlab.com/ee/ci/>`_ for our CI but there are a number of good providers

- `Jupyter Notebooks <https://medium.com/codingthesmartway-com-blog/getting-started-with-jupyter-notebook-for-python-4e7082bd5d46>`_

    - Jupyter is automatically included in your virtual environment if you follow our `Getting setup`_ instructions

- Sphinx_


Formatting
----------

To help us focus on what the code does, not how it looks, we use a couple of automatic formatting tools.
These automatically format the code for us and tell use where the errors are.
To use them, after setting yourself up (see `Getting setup`_), simply run ``make format``.

Buiding the docs
----------------

After setting yourself up (see `Getting setup`_), building the docs is as simple as running ``make docs`` (note, run ``make -B docs`` to force the docs to rebuild and ignore make when it says '... index.html is up to date').
This will build the docs for you.
You can preview them by opening ``docs/build/html/index.html`` in a browser.

For documentation we use Sphinx_.


Docstring style
~~~~~~~~~~~~~~~

For our docstrings we use numpy style docstrings.

For more information on these, `here is the full guide <https://numpydoc.readthedocs.io/en/latest/format.html>`_ and `the quick reference we also use <https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_numpy.html>`_.

If you are using PyCharm, make sure that the numpy doctring style is selected in ``Settings > Tools > Python Integrated Tools``.
This will help automatically generate docstrings.

Why is there a ``Makefile`` in a pure Python repository?
--------------------------------------------------------

Whilst it may not be standard practice, a ``Makefile`` is a simple way to automate general setup (environment setup in particular).
Hence we have one here which basically acts as a notes file for how to do all those little jobs which we often forget e.g. setting up environments, running tests (and making sure we're in the right environment), building docs, setting up auxillary bits and pieces.

.. _Sphinx: http://www.sphinx-doc.org/en/master/
.. _Bookshelf issue tracker: https://gitlab.com/climate-resource/bookshelf/bookshelf/issues
