# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Worldbank Data Indicators
#

# %%
import logging
import re
import tempfile
import zipfile

import pandas as pd
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()
version = "v129"

# %%
metadata = load_nb_metadata("wdi", version=version)
metadata.model_dump()

# %%
local_bookshelf

# %% [markdown]
# # Fetch

# %% [markdown]
# We recommend using `pooch` to download input data. `Pooch` will verify that the
# downloaded file matches the expected hash as a check that the download was performed
# successfully.

# %%

# Data has been cached by CR (hash came from original download)
data_fname = metadata.download_file()

# %%
zf = zipfile.ZipFile(data_fname)
zf.filelist

# %%
try:
    df = pd.read_csv(zf.open("WDICSV.csv"))
except KeyError:
    df = pd.read_csv(zf.open("WDIData.csv"))

column_rename = {
    "Country Name": "name",
    "Country Code": "region",
    "Indicator Name": "variable",
    "Indicator Code": "variable_code",
}
df = df.rename(column_rename, axis=1)
df["scenario"] = "historical"
df["model"] = "World Bank"
df["source"] = f"WDI @ {metadata.version}"
df["unit"] = ""

bad_cols = df.columns[df.columns.str.startswith("Unnamed")]
for col in bad_cols:
    del df[col]

# %%
data = scmdata.ScmRun(df)
data.head()

# %%
unit_regex = re.compile(r"\s\(([^()]*)\)$")


def get_units(run):
    variable = run.get_unique_meta("variable", True)

    unit_match = re.search(unit_regex, variable)
    if unit_match:
        unit = unit_match.group(1)
        run["unit"] = unit
        variable = re.sub(unit_regex, "", variable)
    toks = variable.split(", ")
    variable = "|".join([t.capitalize() for t in toks]).rstrip("|")
    run["variable"] = variable

    return run


# This can take a minute or two
data = data.groupby("variable").apply(get_units)

# %% [markdown]
# ## Emissions cleaning

# %%
print(data.filter(variable="*Gdp*").meta[["variable", "unit"]].drop_duplicates().to_string())

# %%
# Check units
print(data.meta[data.meta.unit.str.contains("kt")][["variable", "unit"]].drop_duplicates().to_string())

# %%
# Fix emissions units to be emissions/yr
data["unit"] = data["unit"].replace("thousand metric tons of CO2 equivalent", "kt CO2/yr")
data["unit"] = data["unit"].replace("kt of CO2 equivalent", "kt CO2/yr")
data["unit"] = data["unit"].replace("Mt of CO2 equivalent", "Mt CO2/yr")
# Check above shows that only emissions ts use "kt" as units; not relevant for current data
data["unit"] = data["unit"].replace("^kt$", "kt CO2/yr", regex=True)
# remove confusing % change timeseries that can easily be reproduced from the remaining data
data = data.filter(unit="% change from *", keep=False)

# %%
# Rename variables
variable_map = {
    # GDP
    "Gdp": "GDP",
    "Gdp|Ppp": "GDP|PPP",
    "Gini index": "Gini Index",
    # Emission variables
    "Agricultural methane emissions": "Emissions|CH4|Agriculture",
    "Agricultural nitrous oxide emissions": "Emissions|N2O|Agriculture",
    "CO2 emissions": "Emissions|CO2",
    "CO2 emissions from electricity and heat production|Total": "Emissions|CO2",
    "CO2 emissions from gaseous fuel consumption": "Emissions|CO2|Gaseous Fuel Consumption",
    "CO2 emissions from liquid fuel consumption": "Emissions|CO2|Liquid Fuel Consumption",
    "CO2 emissions from manufacturing industries and construction": (
        "Emissions|CO2|Manufacturing Industries and Construction"
    ),
    "CO2 emissions from other sectors|Excluding residential buildings and commercial and public services": (
        "Emissions|CO2|Other Sectors"
    ),
    "CO2 emissions from residential buildings and commercial and public services": (
        "Emissions|CO2|Residential Buildings and Commercial and Public Services"
    ),
    "CO2 emissions from solid fuel consumption": "Emissions|CO2|Solid Fuel Consumption",
    "CO2 emissions from transport": "Emissions|CO2|Transport",
    "Energy related methane emissions": "Emissions|CH4|Energy",
    "GHG net emissions/removals by LUCF": "Emissions|GHG|Net LUCF",
    "HFC gas emissions": "Emissions|HFCs",
    "Methane emissions": "Emissions|CH4",
    "Methane emissions in energy sector": "Emissions|CH4|Energy",
    "Nitrous oxide emissions": "Emissions|N2O",
    "Nitrous oxide emissions in energy sector": "Emissions|N2O|Energy",
    "Other greenhouse gas emissions": "Emissions|Other GHGs",
    "Other greenhouse gas emissions|HFC|PFC and SF6": "Emissions|HFCs|PFC and SF6",
    "PFC gas emissions": "Emissions|HFCs|PFC",
    "SF6 gas emissions": "Emissions|HFCs|SF6",
    "Total greenhouse gas emissions": "Emissions|GHG",
    # variables in v129 (and v"33")
    "Carbon dioxide (co2) emissions (total) excluding lulucf": "Emissions|CO2|Total excl. LULUCF",
    "Carbon dioxide (co2) emissions from agriculture": "Emissions|CO2|Agriculture",
    "Carbon dioxide (co2) emissions from building (energy)": "Emissions|CO2|Energy|Buildings",
    "Carbon dioxide (co2) emissions from fugitive emissions (energy)": (
        "Emissions|CO2|Energy|Fugitive Emissions"
    ),
    "Carbon dioxide (co2) emissions from industrial combustion (energy)": (
        "Emissions|CO2|Energy|Industrial Combustion"
    ),
    "Carbon dioxide (co2) emissions from industrial processes": "Emissions|CO2|Industrial Processes",
    "Carbon dioxide (co2) emissions from power industry (energy)": "Emissions|CO2|Energy|Power Industry",
    "Carbon dioxide (co2) emissions from transport (energy)": "Emissions|CO2|Energy|Transport",
    "Carbon dioxide (co2) emissions from waste": "Emissions|CO2|Waste",
    "Carbon dioxide (co2) net fluxes from lulucf - deforestation": "Emissions|CO2|LULUCF|Deforestation",
    "Carbon dioxide (co2) net fluxes from lulucf - forest land": "Emissions|CO2|LULUCF|Forest Land",
    "Carbon dioxide (co2) net fluxes from lulucf - organic soil": "Emissions|CO2|LULUCF|Organic Soil",
    "Carbon dioxide (co2) net fluxes from lulucf - other land": "Emissions|CO2|LULUCF|Other Land",
    "Carbon dioxide (co2) net fluxes from lulucf - total excluding non-tropical fires": (
        "Emissions|CO2|LULUCF|Total Excluding Non-Tropical Fires"
    ),
    "F-gases emissions from industrial processes": "Emissions|F-Gases|Industrial Processes",
    "Methane (ch4) emissions (total) excluding lulucf": "Emissions|CH4|Total excl. LULUCF",
    "Methane (ch4) emissions from agriculture": "Emissions|CH4|Agriculture",
    "Methane (ch4) emissions from building (energy)": "Emissions|CH4|Energy|Building",
    "Methane (ch4) emissions from fugitive emissions (energy)": "Emissions|CH4|Energy|Fugitive Emissions",
    "Methane (ch4) emissions from industrial combustion (energy)": (
        "Emissions|CH4|Energy|Industrial Combustion"
    ),
    "Methane (ch4) emissions from industrial processes": "Emissions|CH4|Industrial Processes",
    "Methane (ch4) emissions from power industry (energy)": "Emissions|CH4|Energy|Power Industry",
    "Methane (ch4) emissions from transport (energy)": "Emissions|CH4|Energy|Transport",
    "Methane (ch4) emissions from waste": "Emissions|CH4|Waste",
    "Nitrous oxide (n2o) emissions (total) excluding lulucf": "Emissions|N2O|Total excl. LULUCF",
    "Nitrous oxide (n2o) emissions from agriculture": "Emissions|N2O|Agriculture",
    "Nitrous oxide (n2o) emissions from building (energy)": "Emissions|N2O|Energy|Building",
    "Nitrous oxide (n2o) emissions from fugitive emissions (energy)": (
        "Emissions|N2O|Energy|Fugitive Emissions"
    ),
    "Nitrous oxide (n2o) emissions from industrial combustion (energy)": (
        "Emissions|N2O|Energy|Industrial Combustion"
    ),
    "Nitrous oxide (n2o) emissions from industrial processes": "Emissions|N2O|Industrial Processes",
    "Nitrous oxide (n2o) emissions from power industry (energy)": "Emissions|N2O|Energy|Power Industry",
    "Nitrous oxide (n2o) emissions from transport (energy)": "Emissions|N2O|Energy|Transport",
    "Nitrous oxide (n2o) emissions from waste": "Emissions|N2O|Waste",
    "Total greenhouse gas emissions excluding lulucf": "Emissions|GHG|Total excl. LULUCF",
    "Total greenhouse gas emissions including lulucf": "Emissions|GHG",
}

for old, new in variable_map.items():
    data["variable"] = data["variable"].replace(old, new)

# %%
data.filter(variable="Emissions*").meta[["variable", "unit"]].drop_duplicates()

# %% [markdown]
# ## Population

# %%
data.filter(variable="*Pop*").get_unique_meta("variable")

# %%
data.filter(variable="Population|*").meta[["variable", "unit"]].drop_duplicates()

# %%
data.get_unique_meta("variable")

# %%
data.filter(variable="GDP")

# %%
data.filter(variable="GDP|PPP", unit="constant * international $").lineplot(units="region", estimator=None)

# %% [markdown]
# # Process

# %%
data["source"] = f"{metadata.name}@{metadata.long_version()}"
data.get_unique_meta("region")

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
# Entire dataset (~168 MB uncompressed)
book.add_timeseries("clean", data, write_long=False)

# %%
data.filter(variable="GDP").get_unique_meta("unit")

# %%
# Smaller subset of data that is typically used for analysis
subset = scmdata.run_append(
    [
        data.filter(variable="GDP*"),
        data.filter(variable="Gini Index"),
        data.filter(variable="Emissions|*"),
        data.filter(variable="Population|Total"),
    ]
)
book.add_timeseries("core", subset)

# %%
subset.meta[["variable", "unit"]].drop_duplicates()

# %%
book.metadata()

# %%
