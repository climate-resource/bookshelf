# Book data analysis example

## Loading a dataset

Begin by initializing a `BookShelf` object. Specify the desired volume and version to
retrieve the corresponding book:

```python
from scmdata import ScmRun
from bookshelf import BookShelf

shelf = BookShelf()

volume = "volume"
version = "v2.3.1"
book = shelf.load(volume, version=version)
```

Once the book is loaded, access specific timeseries data in a wide format by using the
`timeseries` function and specifying the book name. This data will be returned as an
scmdata.ScmRun object. Alternatively, use the `get_long_format_data` function to obtain
timeseries data in a long format, which returns a pd.DataFrame object:

```python
data_wide = book.timeseries('book_of_interest')
data_long = book.get_long_format_data('book_of_interest')
```

## Filtering data

For data in wide format, use the `filter` method from [ScmData](https://scmdata.readthedocs.io/en/latest/notebooks/scmrun.html#operations-with-scalars)
to refine the dataset based on specific metadata criteria:

```python
data_wide.filter(variable="Emissions|CO2|MAGICC AFOLU")
```

For long format data, employ `pandas` functionality to apply necessary filters.


## Plotting

Visualize your data using built-in plotting functions from[ScmData](https://scmdata.readthedocs.io/en/latest/notebooks/plotting-with-seaborn.html).
For instance, to generate a line plot based on filtered metadata:

```python
data_wide.filter(variable="Effective Radiative Forcing").lineplot()
```

This approach allows you to efficiently load, filter, and visualize datasets from your bookshelf,
facilitating in-depth analysis and insights.
