# Updating WDI

* Download data from https://datacatalog.worldbank.org/search/dataset/0037712
* Upload to s3 `aws-vault exec cr-prod -- aws s3 cp  ~/Downloads/WDI_CSV_2024_10_24.zip s3://cr-public-data/_cache/wdi/v33/WDI_CSV_2024_10_24.zip`
* Add metadata `wdi.yaml`
* Publish `aws-vault exec cr-prod -- uv run bookshelf publish wdi --version v33`
