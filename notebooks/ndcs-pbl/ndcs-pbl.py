# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import json
import tempfile
import urllib.request

import pandas as pd
import pycountry
from scmdata import ScmRun

from bookshelf import LocalBook
from bookshelf.dataset_structure import print_dataset_structure
from bookshelf_producer.notebook import load_nb_metadata

# %%
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
metadata = load_nb_metadata("ndcs-pbl")
metadata.dict()


# %%
def get_PBL_countries() -> dict[str, str]:
    """
    Retrieve country names and 3 letter code for countries in PBL

    Retrieve the country names and their corresponding ISO 3166-1 alpha-3 codes using the pycountry
    package. The function further supplements the country list with specific country names
    present in the PBL dataset that do not directly align with names in the pycountry package.

    Returns
    -------
    dict
        A dictionary mapping country names (keys) to their ISO 3166-1 alpha-3 codes (values).

    Notes
    -----
    The supplementary country names and their corresponding codes are manually defined
    within the function to ensure accuracy for specific cases not handled by pycountry.
    """
    countries = {}
    supplementary_countries = {
        "Bolivia": "BOL",
        "Brunei": "BRN",
        "Cape Verde": "CPV",
        "Congo, Democratic Republic": "COD",
        "Congo, Republic": "COG",
        "Cote d' Ivoire": "CIV",
        "Czech Republic": "CZE",
        "Iran": "IRN",
        "North Korea": "PRK",
        "South Korea": "KOR",
        "Laos": "LAO",
        "Macedonia": "MKD",
        "Micronesia (Federated States)": "FSM",
        "Moldova": "MDA",
        "Netherlands Antilles": "ANT",
        "Serbia and Montenegro": "SRB MNE",
        "St. Kitts and Nevis": "KNA",
        "St. Lucia": "LCA",
        "St. Vincent and the Grenadines": "VCT",
        "Swaziland": "SWZ",
        "Syria": "SYR",
        "Taiwan": "TWN",
        "Tanzania": "TZA",
        "Venezuela": "VEN",
        "Vietnam": "VNM",
        "Virgin Island (Br.)": "VGB",
        "EU27": "EU27",
        "Global (harmonised) excl. surplus": "Global (harmonised) excl. surplus",
    }
    for country in pycountry.countries:
        countries[country.name] = country.alpha_3

    countries.update(supplementary_countries)

    return countries


# %%
# Read the raw data from the URL data source, decode and load it as a JSON object
url = "https://themasites.pbl.nl/o/climate-ndc-policies-tool/data/pledges_data.php"
x = urllib.request.urlopen(url)
raw_data = x.read()
encoding = x.info().get_content_charset("utf8")
data = json.loads(raw_data.decode(encoding))

# %%
VALUE_LEN = 1
BOUND_LEN = 2
output = []
countries = get_PBL_countries()
year_lst = list(range(1990, 2031))

# Metadata fields of interest
interested_meta = ["name", "lulucf"]
unit_mapping = {
    "emissions": "Mt CO2/yr",
    "gdp": "10^12 $/Currency",
    "population": "Mio",
}

# Iterate through the provided data, which is expected to be a dictionary of countries or regions'
for k, v in data.items():
    meta_dict = {
        "source": "PBL",
        "source_version": metadata.version,
        "model": None,
        "scenario": None,
    }
    variable_names = []

    for key, value in v.items():
        # Separate variable data (e.g., emissions, GDP, population) from metadata (e.g., name etc.)
        if isinstance(value, dict):  # Data associated with a variable
            variable_names.append(key)
        elif key in interested_meta:  # Metadata of interest
            meta_dict[key] = value

    # Map country names to their respective regions
    if meta_dict["name"] in countries:
        meta_dict["region"] = countries[meta_dict["name"]]

    # If country name is blank, use name as fallback
    else:
        meta_dict["region"] = meta_dict["name"]

    # For each variable, extract and format data for each scenario
    for variable in variable_names:
        for scenario, stats in v[variable].items():
            # Separate logic for handling 'ndcs' as it has a different format
            if scenario != "ndcs":  # General case
                timeseries_dict = {year: None for year in year_lst}
                for timestamp in stats:
                    time, numbers = timestamp[0], timestamp[1:]
                    if len(numbers) == VALUE_LEN:
                        number = numbers[0]
                    elif len(numbers) == BOUND_LEN:  # Bounds given, e.g., [lower_bound, upper_bound]
                        number = tuple(numbers)

                    timeseries_dict[time] = number

                common_meta = {
                    "scenario": scenario,
                    "conditionality": None,
                    "unit": unit_mapping[variable],
                    "variable": variable,
                }

                # If data includes bounds, split into low and high
                if any([isinstance(i, tuple) for i in timeseries_dict.values()]):
                    low_timerseries_dict = {}
                    high_timerseries_dict = {}
                    for key, value in timeseries_dict.items():
                        if type(value) == tuple:
                            if value[0] is None or value[1] is None:
                                low_timerseries_dict[key] = value[0]
                                high_timerseries_dict[key] = value[1]
                            elif value[0] <= value[1]:
                                low_timerseries_dict[key] = value[0]
                                high_timerseries_dict[key] = value[1]
                            else:
                                low_timerseries_dict[key] = value[1]
                                high_timerseries_dict[key] = value[0]
                        else:
                            low_timerseries_dict[key] = value

                    output.append(
                        {
                            **meta_dict,
                            "ambition": "low",
                            **common_meta,
                            **low_timerseries_dict,
                        }
                    )
                    output.append(
                        {
                            **meta_dict,
                            "ambition": "high",
                            **common_meta,
                            **high_timerseries_dict,
                        }
                    )
                else:
                    output.append(
                        {
                            **meta_dict,
                            "ambition": None,
                            **common_meta,
                            **timeseries_dict,
                        }
                    )
            else:
                # 'ndcs' scenario requires special handling
                ncds_rows = {}
                for label, number in stats.items():
                    # extract the digits that represents the year in ncds labels
                    year = "".join(c for c in label if c.isdigit())

                    year = int("20" + year)

                    # store the text info which represents the conditionality and ambitions of the ndcs value
                    ncds_scenario = "".join(c for c in label if not c.isdigit()).replace("__", "_")

                    # add the ndcs value to the corresponding year
                    if ncds_scenario in ncds_rows:
                        ncds_rows[ncds_scenario][year] = number
                    else:
                        ncds_rows[ncds_scenario] = {year: None for year in year_lst}
                        ncds_rows[ncds_scenario][year] = number

                for ncds_scenario, timeseries_dict in ncds_rows.items():
                    output.append(
                        {
                            **meta_dict,
                            "ambition": None,
                            "scenario": "ndcs",
                            "conditionality": ncds_scenario,
                            "unit": unit_mapping[variable],
                            "variable": variable,
                            **timeseries_dict,
                        }
                    )

output_df = pd.DataFrame(output)

# %%
# output_df ambition
output_df.loc[output_df["conditionality"].str.contains("l", na=False), "ambition"] = "low"
output_df.loc[output_df["conditionality"].str.contains("h", na=False), "ambition"] = "high"
output_df.loc[output_df["scenario"].str.contains("m", na=False), "ambition"] = "mean"

# output_df category
output_df.loc[output_df["scenario"] == "boundm", "scenario"] = "bound"
output_df.loc[output_df["scenario"] == "degreem", "scenario"] = "degree"
output_df.loc[output_df["scenario"] == "degreem15", "scenario"] = "degree15"
output_df.loc[output_df["conditionality"].str.contains("p_", na=False), "scenario"] = "pledge ndcs"

# output_df category
output_df.loc[output_df["conditionality"].str.contains("_p", na=False), "scenario"] = "Initial NDC"
output_df.loc[output_df["conditionality"].str.contains("l_c", na=False), "scenario"] = "Updated NDC"
output_df.loc[output_df["conditionality"].str.contains("h_c", na=False), "scenario"] = "Updated NDC"
output_df.loc[output_df["scenario"] == "history", "scenario"] = "Historical"

# output_df conditionality
output_df.loc[output_df["conditionality"].str.contains("_con", na=False), "conditionality"] = "conditional"
output_df.loc[output_df["conditionality"].str.contains("_ucon", na=False), "conditionality"] = "unconditional"

# variable
output_df.loc[output_df["variable"] == "emissions", "variable"] = "Emissions|Total GHG"

output_df.loc[output_df["variable"] == "population", "variable"] = "Population"
output_df.loc[output_df["variable"] == "gdp", "variable"] = "GDP"

# category
output_df.loc[
    (output_df["variable"] == "Emissions|Total GHG") & (output_df["lulucf"] == "excl"),
    "category",
] = "M.0.EL"
output_df.loc[
    (output_df["variable"] == "Emissions|Total GHG") & (output_df["lulucf"] == "incl"),
    "category",
] = "0"

# %%
assert [value for value in output_df["ambition"].unique().tolist() if value is not None].sort() == [
    "low",
    "high",
    "mean",
].sort()

assert (
    output_df["scenario"].unique().tolist().sort()
    == [
        "Historical",
        "bound",
        "degree",
        "degree15",
        "pbl",
        "national",
        "pledge ndcs",
        "Updated NDC",
        "Initial NDC",
    ].sort()
)
assert [value for value in output_df["conditionality"].unique().tolist() if value is not None].sort() == [
    "conditional",
    "unconditional",
].sort()
assert output_df["variable"].unique().tolist().sort() == ["Emissions|Total GHG", "Population", "GDP"].sort()
assert output_df["category"].unique().tolist().sort() == ["M.0.EL", "nan", "0"].sort()


# %%
PBL_df_ScmRun = ScmRun(output_df)

# %%
PBL_df_ScmRun.timeseries()

# %%
print_dataset_structure(PBL_df_ScmRun)

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("pbl", PBL_df_ScmRun)

# %%
book.metadata()

# %%
