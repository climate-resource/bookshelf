# %%
import json
import tempfile
import urllib.request

import pandas as pd
import pycountry
from scmdata import ScmRun

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %%
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
metadata = load_nb_metadata("pbl")
metadata.dict()


# %%
def get_PBL_countries() -> dict:
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
BOUD_RANGE_LEN = 2
output = []
countries = get_PBL_countries()
year_lst = list(range(1990, 2031))

# Metadata fields of interest
interested_meta = ["name", "lulucf"]
unit_mapping = {
    "emissions": "Mt CO2eq/yr",
    "gdp": "10^12 $/Currency",
    "population": "Mio",
}

# Iterate through the provided data, which is expected to be a dictionary of countries or regions'
for k, v in data.items():
    meta_dict = {"model": "PBL", "model_version": "18April2023_PBL", "scenario": None}
    variable_names = []

    for key, value in v.items():
        # Separate variable data (e.g., emissions, GDP, population) from metadata (e.g., name etc.)
        if type(value) == dict:  # Data associated with a variable
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
                    elif (
                        len(numbers) == BOUD_RANGE_LEN
                    ):  # Bounds given, e.g., [lower_bound, upper_bound]
                        number = tuple(numbers)

                    timeseries_dict[time] = number

                # If data includes bounds, split into low and high
                if any([type(i) == tuple for i in timeseries_dict.values()]):
                    low_timerseries_dict = {
                        k: (v[0] if type(v) == tuple else v) for k, v in timeseries_dict.items()
                    }
                    high_timerseries_dict = {
                        k: (v[1] if type(v) == tuple else v) for k, v in timeseries_dict.items()
                    }
                    output.append(
                        {
                            **meta_dict,
                            "ambition": "low",
                            "category": scenario,
                            "conditionality": None,
                            "unit": unit_mapping[variable],
                            "variable": variable,
                            **low_timerseries_dict,
                        }
                    )
                    output.append(
                        {
                            **meta_dict,
                            "ambition": "high",
                            "category": scenario,
                            "conditionality": None,
                            "unit": unit_mapping[variable],
                            "variable": variable,
                            **high_timerseries_dict,
                        }
                    )
                else:
                    output.append(
                        {
                            **meta_dict,
                            "ambition": None,
                            "category": scenario,
                            "conditionality": None,
                            "unit": unit_mapping[variable],
                            "variable": variable,
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
                            "category": "ndcs",
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
output_df.loc[output_df["category"].str.contains("m", na=False), "ambition"] = "mean"

# output_df category
output_df.loc[output_df["category"] == "boundm", "category"] = "bound"
output_df.loc[output_df["category"] == "degreem", "category"] = "degree"
output_df.loc[output_df["category"] == "degreem15", "category"] = "degree15"
output_df.loc[output_df["conditionality"].str.contains("p_", na=False), "category"] = "pledge ndcs"

# output_df category
output_df.loc[output_df["conditionality"].str.contains("_p", na=False), "category"] = "Initial NDC"
output_df.loc[output_df["conditionality"].str.contains("l_c", na=False), "category"] = "Updated NDC"
output_df.loc[output_df["conditionality"].str.contains("h_c", na=False), "category"] = "Updated NDC"
output_df.loc[output_df["category"] == "history", "category"] = "Historical"

# output_df conditionality
output_df.loc[
    output_df["conditionality"].str.contains("_con", na=False), "conditionality"
] = "conditional"
output_df.loc[
    output_df["conditionality"].str.contains("_ucon", na=False), "conditionality"
] = "unconditional"

# variable
output_df.loc[
    (output_df["variable"] == "emissions") & (output_df["lulucf"] == "excl"), "variable"
] = "Emissions|Total GHG excl. LULUCF"
output_df.loc[
    (output_df["variable"] == "emissions") & (output_df["lulucf"] == "incl"), "variable"
] = "Emissions|Total GHG incl. LULUCF"
output_df.loc[output_df["variable"] == "population", "variable"] = "Population"
output_df.loc[output_df["variable"] == "gdp", "variable"] = "GDP"

# %%
PBL_df_ScmRun = ScmRun(output_df)

# %%
PBL_df_ScmRun.timeseries()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("pbl", PBL_df_ScmRun)

# %%
book.metadata()
