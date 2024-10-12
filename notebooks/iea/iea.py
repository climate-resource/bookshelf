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
import tempfile

import pandas as pd
import pycountry
import requests
import tqdm
from scmdata import ScmRun

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %%
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
metadata = load_nb_metadata("iea")
metadata.dict()

# %%
iso3_url = "https://api.iea.org/ndc/list/iso3"
ndc_url = "https://api.iea.org/ndc?iso3="
totoco2 = "https://api.iea.org/stats/indicator/TotCO2?countries="

# %%
iso3 = requests.get(iso3_url, timeout=800).json()
ndc = []
totco2 = []
for country in tqdm.tqdm(iso3):
    ndc_data = requests.get(ndc_url + str(country), timeout=800).json()
    totco2_data = requests.get(totoco2 + str(country), timeout=800).json()
    ndc.append(ndc_data)
    totco2.append(totco2_data)

# %%
output_ndc = []
for ndc_target_list in ndc:
    if not ndc_target_list:
        continue

    for ndc_target in ndc_target_list:
        output_ndc.append(ndc_target)

# %%
output_ndc_df = pd.DataFrame(output_ndc)
output_ndc_df

# %%
output_totco2 = []
for totco2_group in totco2:
    if not totco2_group:
        continue

    for co2_emms_yr in totco2_group:
        output_totco2.append(co2_emms_yr)

# %%
output_totco2_df = pd.DataFrame(output_totco2)

# %%
output_totco2_df = output_totco2_df.rename(
    columns={"country": "region", "seriesLabel": "variable", "units": "unit"}
)
output_totco2_df["category"] = "1"
output_totco2_df["variable"] = "Emissions|CO2"
output_totco2_df["scenario"] = None
output_totco2_df["source"] = "IEA"
output_totco2_df["source_version"] = metadata.version
output_totco2_df["model"] = None
output_totco2_df["conditionality"] = "unconditional"
output_totco2_df["unit"] = output_totco2_df["unit"].map({"Mt of CO2": "MtCO2/yr"})

# %%
output_totco2_df = output_totco2_df.drop(columns=["flowLabel", "flowOrder", "flow"])

# %%
output_totco2_df = output_totco2_df.drop_duplicates()

# %%
for index, row in output_totco2_df.iterrows():
    region = row["region"]
    region_lst = pycountry.countries.get(alpha_3=region)
    if region_lst is not None:
        output_totco2_df.loc[index, "name"] = region_lst.name
    else:
        output_totco2_df.loc[index, "name"] = None


# %%
output_totco2_df = output_totco2_df.drop("short", axis=1)

# %%
output_totco2_df = output_totco2_df.pivot_table(
    index=[
        "name",
        "variable",
        "unit",
        "region",
        "category",
        "scenario",
        "model",
        "model_version",
        "conditionality",
    ],
    columns="year",
    values="value",
)

# %%
output_totco2_df

# %%
output_totco2_ScmRun = ScmRun(output_totco2_df)

# %%
output_totco2_ScmRun.timeseries()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("iea_energy_sector_co2_emissions", output_totco2_ScmRun)

# %%
book.metadata()
