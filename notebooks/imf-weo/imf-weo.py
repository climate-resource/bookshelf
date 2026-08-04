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
import re
import tempfile

import pandas as pd
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()
version = "v202603"

# %%
metadata = load_nb_metadata("imf-weo", version=version)
metadata.model_dump()


# %%
local_file = metadata.download_file()
local_file

# %%
# A handful of units are missing in the xlsx compared to the old data
UNIT_OVERRIDES = {
    "LE": "Persons",
    "LP": "Persons",
    "LUR": "Percent of total labor force",
    "NGDPRPPPPC": "International dollar",
    "PPPEX": "Domestic currency per current international dollar",
    "PPPGDP": "International dollar",
    "PPPPC": "International dollar",
}


def read_imf_weo_xlsx(local_file) -> pd.DataFrame:
    """Read the new xlsx format and transform it to look like the old for following manipulation."""
    raw = pd.read_excel(local_file, sheet_name="Countries")

    # Unit/Scale are properties of the indicator rather than the country, but are only
    # populated on a subset of rows for a given indicator
    def fill(s):
        return s.ffill().bfill()

    raw[["UNIT", "SCALE"]] = raw.groupby("INDICATOR.ID")[["UNIT", "SCALE"]].transform(fill)
    raw["UNIT"] = raw["UNIT"].fillna(raw["INDICATOR.ID"].map(UNIT_OVERRIDES))

    still_missing = sorted(raw.loc[raw["UNIT"].isna(), "INDICATOR.ID"].unique())
    if still_missing:
        raise ValueError(
            f"No Unit could be determined for indicator code(s) {still_missing}; add them to UNIT_OVERRIDES"
        )

    year_columns = [c for c in raw.columns if isinstance(c, int)]
    if not year_columns:
        raise ValueError("No year columns found in the 'Countries' sheet; column layout may have changed")
    weo_data = raw.rename(
        {
            "COUNTRY.ID": "ISO",
            "COUNTRY": "Country",
            "INDICATOR": "Subject Descriptor",
            "INDICATOR.ID": "WEO Subject Code",
            "UNIT": "Units",
            "SCALE": "Scale",
        },
        axis=1,
    )
    id_columns = ["ISO", "Country", "Subject Descriptor", "WEO Subject Code", "Units", "Scale"]
    weo_data = weo_data[[*id_columns, *year_columns]]
    return weo_data.rename(columns={c: str(c) for c in year_columns})


if local_file.endswith(".xlsx"):
    weo_data = read_imf_weo_xlsx(local_file)
else:
    encoding = "UTF-16 LE"
    if version == "v202310":
        encoding = "Windows 1252"
    # Last 2 rows are footer notes, not data
    weo_data = pd.read_csv(local_file, encoding=encoding, sep="\t", thousands=",").iloc[:-2]
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
    )

    unnamed_columns = weo_data.columns[weo_data.columns.str.contains("Unnamed: ")]
    weo_data = weo_data.drop(unnamed_columns, axis=1)

    weo_data = weo_data.drop(["WEO Country Code"], axis=1, errors="ignore")
    weo_data["model"] = "IMF WEO"
    weo_data["scenario"] = ""
    weo_data["source"] = f"IMF WEO @ {metadata.version}"

    def clean_data(d):
        if d.dtype == object:
            d = d.str.replace(",", "").str.replace("--", "")
        return pd.to_numeric(d)

    for i in range(1980, end_year + 1):
        if str(i) not in weo_data.columns:
            continue
        weo_data[str(i)] = clean_data(weo_data[str(i)])

    drop_meta_cols = [
        c
        for c in ["Country", "Country/Series-specific Notes", "Subject Notes", "Estimates Start After"]
        if c in weo_data.columns
    ]
    return scmdata.ScmRun(weo_data).drop_meta(drop_meta_cols)


imf_ts = read_imf_weo(weo_data)

# %%
imf_ts.meta[["variable", "unit"]].drop_duplicates()

# %%
# Tweak metadata for GDP|PPP

# Convert GDP billions to $
imf_gdp_ppp = imf_ts.filter(variable_code="PPPGDP") * 1e9
if any(x != "Billions" for x in imf_gdp_ppp["Scale"]):
    raise ValueError("unexpected variable scale for variable PPPGDP")
imf_gdp_ppp["unit"] = "current international $"
imf_gdp_ppp["variable"] = "GDP|PPP"
imf_gdp_ppp["Scale"] = "Units"

imf_ts = scmdata.run_append([imf_ts.filter(variable_code="PPPGDP", keep=False), imf_gdp_ppp])

# %%
# calculate GDP|PPP|Constant from available data

# assume the reference year is defined by the latest ICP Benchmark mentioned in the variable description
(ngdprpppc_descriptor,) = imf_ts.filter(variable_code="NGDPRPPPPC").get_unique_meta("variable")
icp_benchmark_years = re.findall(r"ICP benchmarks?\s+(?:\d{4}-)?(\d{4})", ngdprpppc_descriptor)
if len(icp_benchmark_years) != 1:
    raise ValueError(
        f"Expected exactly one ICP benchmark year in {ngdprpppc_descriptor!r}, found {icp_benchmark_years}"
    )
(icp_benchmark_year,) = icp_benchmark_years

if any(x != "Millions" for x in imf_ts.filter(variable_code="LP")["Scale"]):
    raise ValueError("unexpected variable scale for variable LP")
if any(x != "Units" for x in imf_ts.filter(variable_code="NGDPRPPPPC")["Scale"]):
    raise ValueError("unexpected variable scale for variable NGDPRPPPPC")

imf_constant_ts = []
for region in imf_ts.get_unique_meta("region"):
    imf_data = imf_ts.filter(region=region, variable_code=["NGDPRPPPPC"]).multiply(
        imf_ts.filter(region=region, variable_code=["LP"]) * 1e6,
        op_cols={
            "unit": f"constant {icp_benchmark_year} international $",
            "variable": "GDP|PPP|Constant",
            "variable_code": "n/a (calculated NGDPRPPPPC*LP)",
            "Scale": "Units",
        },
    )
    imf_constant_ts.append(imf_data)

imf_constant_ts = scmdata.run_append(imf_constant_ts)
imf_constant_ts.meta[["variable", "unit"]].drop_duplicates()
imf_ts = scmdata.run_append([imf_ts, imf_constant_ts])

# %%
# filter out any all-nan rows or columns in imf_ts
imf_ts_data = imf_ts.timeseries().dropna(axis=0, how="all").dropna(axis=1, how="all")
print(f"shape {imf_ts.shape} -> {imf_ts_data.shape} after dropna")
imf_ts = scmdata.ScmRun(imf_ts_data)

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("by_country", imf_ts)

# %%
book.metadata()
