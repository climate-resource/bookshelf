# Resource Types

A Book can contain multiple resources, each representing a different dataset or table.
 Resources are distinguished by their **type**, which determines how the data is stored and accessed.

## Available Types

| Type         | Return Type      | Method                  | Description                    |
| ------------ | ---------------- | ----------------------- | ------------------------------ |
| `timeseries` | `scmdata.ScmRun` | `book.timeseries(name)` | IAMC-formatted timeseries data |
| `dataframe`  | `pd.DataFrame`   | `book.dataframe(name)`  | Arbitrary tabular data         |

## Timeseries

Timeseries resources store IAMC-formatted data with standardized metadata columns and year columns for temporal data.

**Required columns:**

| Column | Description |
| ------ | ----------- |
| `model` | Model that produced the data |
| `scenario` | Scenario name |
| `region` | Geographic region |
| `variable` | Variable name (hierarchical, e.g., `Emissions\|CO2\|Energy`) |
| `unit` | Unit of measurement |

```python
from bookshelf import BookShelf

book = BookShelf().load("rcmip-emissions", "v5.1.0")
emissions = book.timeseries("complete")

# Returns an scmdata.ScmRun object
emissions.filter(variable="Emissions|CO2|MAGICC AFOLU").head()
```

**Use for:**

- Emissions projections
- Climate model outputs
- Scenario data
- Any data following the IAMC template

**Supported formats:** Wide format (years as columns) and long format (year as a column).

## DataFrame

DataFrame resources store arbitrary tabular data that doesn't fit the timeseries model, such as metadata tables, lookup data, or reference information.

```python
book = BookShelf().load("wdi", "v33")
countries = book.dataframe("country_metadata")

# Returns a pandas DataFrame
countries.head()
```

**Use for:**

- Country/region metadata
- Variable mappings and definitions
- Lookup tables
- Any flat tabular data

**Supported column types:**

| Type        | Description    | Example Values             |
| ----------- | -------------- | -------------------------- |
| `int`       | Integer values | `331000000`, `42`          |
| `float`     | Floating point | `65280.5`, `3.14`          |
| `str`       | Text strings   | `"USA"`, `"North America"` |
| `bool`      | Boolean        | `True`, `False`            |
| `datetime`  | Timestamps     | `2024-01-15 10:30:00`      |
| `timedelta` | Durations      | `1 day`, `2 hours`         |

**Constraints:**

- Columns must be flat (no MultiIndex)
- Index must be flat (no MultiIndex)
- Named indices are converted to columns on storage
