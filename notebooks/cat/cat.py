# %%
import glob
import os
import pathlib
import tempfile

import pandas as pd
import pycountry
from scmdata import ScmRun

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %%
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
metadata = load_nb_metadata("cat")
metadata.dict()

# %%
ROOT_DIR = pathlib.Path("cat.py").resolve().parents[1]
RAW_CAT_DATA_DIR = ROOT_DIR / "cat" / "CAT"

csv_files = glob.glob(os.path.join(RAW_CAT_DATA_DIR, "*.xls*"))


# %%
def get_CAT_countries() -> dict:
    """
    Retrieve country names and 3 letter code for countries in CAT

    Retrieve the country names and their corresponding ISO 3166-1 alpha-3 codes using the pycountry
    package. The function further supplements the country list with specific country names
    present in the CAT dataset that do not directly align with names in the pycountry package.

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
        "United States": "USA",
        "European Union": "EU",
        "Vietnam": "VNM",
        "Russia": "RUS",
        "Iran": "IRN",
        "Korea": "KOR",
        "Türkiye": "TUR",
    }

    for country in pycountry.countries:
        countries[country.name] = country.alpha_3

    countries.update(supplementary_countries)

    return countries


# %%
CAT_df = pd.DataFrame()
# Iterate through each Excel file.
for f in csv_files:
    # Skip initial 19 rows which contain dataset descriptions, repeated across files.
    CAT_data = pd.read_excel(open(f, "rb"), sheet_name="Assessment", skiprows=19)
    country_name = CAT_data.iloc[0, 3]

    # Standardize country names to maintain consistency.
    if country_name == "USA":
        country_name = "United States"
    elif country_name == "EU ":
        country_name = "European Union"

    countries = get_CAT_countries()
    # Convert country names to 3-letter country codes (regions).
    if country_name in countries.keys():
        region_name = countries[country_name]

    date = CAT_data.iloc[1, 3]
    CAT_data = CAT_data.iloc[3:, 2:]
    CAT_data.columns = CAT_data.iloc[0]
    CAT_data = CAT_data[1:]

    # Insert meta data columns into dataframe.
    CAT_data.insert(2, "variable", "Total GHG")
    CAT_data.insert(2, "unit", "MtCO2e/yr")
    CAT_data.insert(0, "country", country_name)
    CAT_data.insert(0, "region", str(region_name))
    CAT_data.insert(0, "model_version", date)
    CAT_data.insert(0, "gwp_metric", "AR4GWP100")
    CAT_data.insert(0, "model", "CAT")

    # Consolidate current country's data with main dataframe.
    CAT_df = pd.concat([CAT_df, CAT_data])

CAT_df = CAT_df.rename(columns={"Graph label": "scenario"})

# Create a category column based on the information in the Sector/Type and scenario
CAT_df.loc[
    CAT_df["Sector/Type"].str.contains("Total, excl LULUCF", na=False), "category"
] = "M.0.EL"
CAT_df.loc[CAT_df["Sector/Type"].str.contains("LULUCF", na=False), "category"] = "M.LULUCF"

CAT_df.loc[CAT_df["scenario"].str.contains("Unconditional", na=False), "category"] = "M.0.EL"
CAT_df.loc[CAT_df["scenario"].str.contains("Conditional", na=False), "category"] = "M.0.EL"

# Replace placeholder values ('-') with None.
for year in range(1990, 2051):
    CAT_df[year] = CAT_df[year].replace("-", None)

CAT_df

# %%
# CAT_df.to_csv(constants.PROCESS_DATA_DIR / "CAT.csv", index=False)

# %%
CAT_df_ScmRun = ScmRun(CAT_df)

# %%
CAT_df_ScmRun.timeseries()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("cat", CAT_df_ScmRun)

# %%
book.metadata()
