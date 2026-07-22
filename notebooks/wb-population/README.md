# Updating wb-population

* Download data from <https://datacatalog.worldbank.org/search/dataset/0037655/population-estimates-and-projections>
* Upload to gus `rsync --mkpath ~/Downloads/Population-Estimates_CSV.zip gus:/data/public/_cache/wb-population/v23/Population-Estimates_CSV.zip`
* Edit metadata `wb-population.yaml`
* Publish `aws-vault exec cr-prod -- uv run bookshelf publish wb-population --version v23`
