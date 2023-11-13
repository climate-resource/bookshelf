# %%
import tempfile

import pandas as pd
import pycountry
import requests
import tqdm
from scmdata import ScmRun

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %%
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
metadata = load_nb_metadata("IEA")
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
for i in range(len(ndc)):
    if len(ndc[i]) != 0:
        for j in range(len(ndc[i])):
            output_ndc.append(ndc[i][j])

# %%
output_ndc_df = pd.DataFrame(output_ndc)
output_ndc_df

# %%
output_totco2 = []
for i in range(len(totco2)):
    if len(totco2[i]) != 0:
        for j in range(len(totco2[i])):
            output_totco2.append(totco2[i][j])

# %%
output_totco2_df = pd.DataFrame(output_totco2)

# %%
output_totco2_df = output_totco2_df.rename(
    columns={"country": "region", "short": "name", "seriesLabel": "variable", "units": "unit"}
)
output_totco2_df["scenario"] = "default_scenario"
output_totco2_df["model"] = "IEA model"
output_totco2_df["model_version"] = "IEA_default_model_version"
output_totco2_df["conditionality"] = "unconditional"
output_totco2_df["unit"] = output_totco2_df["unit"].map({"Mt of CO2": "MtCO2e/yr"})

# %%
output_totco2_df = output_totco2_df.drop(columns=["flowLabel", "flowOrder", "flow"])

# %%
output_totco2_df = output_totco2_df.drop_duplicates()

# %%
for index, row in output_totco2_df.iterrows():
    region = row["region"]
    region_lst = pycountry.countries.get(alpha_3=region)
    if region_lst is not None:
        output_totco2_df.loc[index, "country"] = region_lst.name
    else:
        output_totco2_df.loc[index, "country"] = None

# %%
output_totco2_df = output_totco2_df.pivot_table(
    index=[
        "name",
        "variable",
        "unit",
        "region",
        "scenario",
        "model",
        "model_version",
        "conditionality",
        "country",
    ],
    columns="year",
    values="value",
)

# %%
output_totco2_df

# %%
output_totco2_ScmRun2 = ScmRun(output_totco2_df)

# %%
output_totco2_ScmRun2.timeseries()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("totco2", output_totco2_ScmRun2)

# %%
book.metadata()
