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
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()
version = "v202310"

# %%
metadata = load_nb_metadata("imf-weo", version=version)
metadata.dict()


# %%
local_file = metadata.download_file()
local_file

# %%

encoding = "UTF-16 LE"
if version == "v202310":
    encoding = "Windows 1252"
weo_data = pd.read_csv(local_file, encoding=encoding, sep="\t", thousands=",")
weo_data


# %%
def read_imf_weo(df, end_year=2050) -> scmdata.ScmRun:
    weo_data = df.rename(
        {
            "Units": "unit",
            "ISO": "region",
            "Subject Descriptor": "variable",
            "WEO Subject Code": "variable_code",
        },
        axis=1,
    ).iloc[:-2]

    unnamed_columns = weo_data.columns[weo_data.columns.str.contains("Unnamed: ")]
    weo_data = weo_data.drop(unnamed_columns, axis=1)

    weo_data = weo_data.drop(["WEO Country Code"], axis=1)
    weo_data["model"] = "IMF WEO"
    weo_data["scenario"] = ""

    def clean_data(d):
        return pd.to_numeric(d.str.replace(",", "").str.replace("--", ""))

    for i in range(1980, end_year + 1):
        if str(i) not in weo_data.columns:
            continue
        weo_data[str(i)] = clean_data(weo_data[str(i)])

    return scmdata.ScmRun(weo_data).drop_meta(
        [
            "Country",
            "Country/Series-specific Notes",
            "Subject Notes",
            "Estimates Start After",
        ]
    )


imf_ts = read_imf_weo(weo_data)


# %%
# Tweak some metadata

# Convert GDP billions to $
imf_gdp_ppp = imf_ts.filter(variable_code="PPPGDP") * 1e9
imf_gdp_ppp["unit"] = "current international $"
imf_gdp_ppp["variable"] = "GDP|PPP"
imf_gdp_ppp["Scale"] = "Units"

imf_ts = scmdata.run_append([imf_ts.filter(variable_code="PPPGDP", keep=False), imf_gdp_ppp])

# %%
imf_constant_ts = []
for region in imf_ts.get_unique_meta("region"):
    imf_data = imf_ts.filter(region=region, variable_code=["NGDPRPPPPC"]).multiply(
        imf_ts.filter(region=region, variable_code=["LP"]) * 1e6,
        op_cols={
            "unit": "constant 2017 international $",
            "variable": "GDP|PPP|Constant",
            "variable_code": "n/a (calculated NGDPRPPPPC/LP)",
            "Scale": "Units",
        },
    )
    imf_constant_ts.append(imf_data)

imf_constant_ts = scmdata.run_append(imf_constant_ts)
imf_constant_ts

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("by_country", scmdata.run_append([imf_ts, imf_constant_ts]))

# %%
book.metadata()
