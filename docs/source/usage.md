# Usage

TODO: Lots to write

```
>>> import bookshelf
>>> shelf = bookshelf.BookShelf()

# The latest version of book can be retrieved from the shelf
>>> primap_book = shelf.load("primap-hist")

# Alternatively, a specific version of a book can be fetched
>>> primap_book = shelf.load("primap-hist", version="v2.4.2")

# Timeseries data can be fetched.
>>> primap_book.timeseries('by_coutry')
<ScmRun (timeseries: 34834, timepoints: 272)>
Time:
        Start: 1750-01-01T00:00:00
        End: 2021-01-01T00:00:00
Meta:
               category      country gwp_context        model region                     scenario                       source          unit             variable
        0             0  Afghanistan   AR4GWP100  PRIMAP-hist    AFG  Historical|Country Reported  PRIMAP-hist_v2.4.1_final_nr  CO2 * kt / a  Emissions|Kyoto GHG
        1             0  Afghanistan   AR4GWP100  PRIMAP-hist    AFG       Historical|Third Party  PRIMAP-hist_v2.4.1_final_nr  CO2 * kt / a  Emissions|Kyoto GHG
        2             0  Afghanistan   SARGWP100  PRIMAP-hist    AFG  Historical|Country Reported  PRIMAP-hist_v2.4.1_final_nr  CO2 * kt / a  Emissions|Kyoto GHG
        3             0  Afghanistan   SARGWP100  PRIMAP-hist    AFG       Historical|Third Party  PRIMAP-hist_v2.4.1_final_nr  CO2 * kt / a  Emissions|Kyoto GHG
        4             0  Afghanistan         NaN  PRIMAP-hist    AFG  Historical|Country Reported  PRIMAP-hist_v2.4.1_final_nr  CH4 * kt / a        Emissions|CH4
        ...         ...          ...         ...          ...    ...                          ...                          ...           ...                  ...
        34829  M.LULUCF     Zimbabwe   SARGWP100  PRIMAP-hist    ZWE       Historical|Third Party  PRIMAP-hist_v2.4.1_final_nr  CO2 * kt / a  Emissions|Kyoto GHG
        34830  M.LULUCF     Zimbabwe         NaN  PRIMAP-hist    ZWE  Historical|Country Reported  PRIMAP-hist_v2.4.1_final_nr  CO2 * kt / a        Emissions|CO2
        34831  M.LULUCF     Zimbabwe         NaN  PRIMAP-hist    ZWE  Historical|Country Reported  PRIMAP-hist_v2.4.1_final_nr  N2O * kt / a        Emissions|N2O
        34832  M.LULUCF     Zimbabwe         NaN  PRIMAP-hist    ZWE       Historical|Third Party  PRIMAP-hist_v2.4.1_final_nr  CO2 * kt / a        Emissions|CO2
        34833  M.LULUCF     Zimbabwe         NaN  PRIMAP-hist    ZWE       Historical|Third Party  PRIMAP-hist_v2.4.1_final_nr  N2O * kt / a        Emissions|N2O

        [34834 rows x 9 columns]
```
