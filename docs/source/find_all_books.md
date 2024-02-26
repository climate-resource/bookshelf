# Finding the available books

The `bookshelf` library hosts a multitude of volumes, each with various
versions or books. Below is a guide to discovering all available books.

### Finding all available volumes and versions

To enumerate all volumes along with their versions, begin by identifying
the root directory where the notebooks generating these books are located,
accessible via the `NOTEBOOK_DIRECTORY`. Subsequently, leverage the
`get_available_versions` function to ascertain all versions for each volume.

```python
from bookshelf.notebook import (
    get_available_versions,
    get_notebook_directory,
)
from glob import glob
import os

NOTEBOOK_DIRECTORY = get_notebook_directory()
notebooks = glob(os.path.join(NOTEBOOK_DIRECTORY, "**", "*.py"), recursive=True)

books_info = []
for nb in notebooks:
    versions = get_available_versions(nb.replace(".py", ".yaml"), include_private=False)
    notebook_name = os.path.basename(nb)[:-3]
    books_info.extend((nb, notebook_name, v) for v in versions)

books_info
```

This method provides a comprehensive list of all available volumes along with their versions,
facilitating easy access and management of the books within the bookshelf.
