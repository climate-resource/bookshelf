# Simplify Publishing Workflow for Data Producers

## Problem

The current publishing workflow requires data producers to create Jupytext notebooks with specific boilerplate structure, even for simple datasets that don't need complex transformations. This creates friction:

1. **Notebook boilerplate is heavy** - Every notebook requires ~50 lines of setup (Jupytext header, parameters cell with exact tags, metadata loading, LocalBook creation pattern) for what might be 3 lines of actual data processing logic.

2. **Debugging is painful** - Notebooks execute via papermill in isolated environments. When something fails mid-execution, diagnosing the issue requires understanding the jupytext -> ipynb -> papermill pipeline.

3. **No direct API for power users** - Programmatic publishing (CI/CD pipelines, scripts, batch processing) must still go through the notebook abstraction.

The core value of bookshelf is **semi-structured, versioned, reusable data** - notebooks are a means to an end, not the goal.
It should be easy for a developer to register a new artefact as part of a processing pipeline.

The original idea was to publish the notebooks alongside the data and render them in a website.
This would still be a useful outcome, but not the primary outcome.

## What Already Exists

`LocalBook` already supports direct creation without notebooks:

```python
book = LocalBook.create_new("my-data", "v1.0.0", edition=1, local_bookshelf=path)
book.add_timeseries("emissions", scmrun_data)
book.add_dataframe("metadata", df)
```

This path exists but has gaps (actually pubishing) that make it impractical for real use.

## Gaps in the Direct API

| Gap                                              | Impact                                                                  |
| ------------------------------------------------ | ----------------------------------------------------------------------- |
| No `publish()` on LocalBook                      | Must manually construct BookShelf + call `actions.publish(shelf, book)` |
| `create_new()` doesn't accept license/metadata   | Published books missing required catalog fields                         |
| No source file download helper outside notebooks | `NotebookMetadata.download_file()` requires YAML config parsing         |
| Publishing requires understanding internals      | No documented "happy path" for non-notebook publishing                  |

## What Metadata Is Actually Required?

**Technically required for publishing:**

- `name` - S3 path construction
- `version` - S3 path construction
- `edition` - S3 path construction
- Resource file hashes - computed automatically

**Required for volume catalog:**

- `license` - stored in volume.json (currently can be empty string)

**Optional (just stored, not enforced (yet)):**

- `private` - defaults to False
- `description`, `author`, `author_email`
- `data_dictionary` - validation schema, not enforced
- `dataset.url`, `dataset.doi` - provenance metadata

**Whats missing**

- git information (particularly useful if produced in a pipeline)
- links to other datasets
- category/metadata to group or organise

## Proposed Solutions

### Option A: Minimal - Enhance LocalBook

Add what's missing to make the existing direct path usable:

```python
# Enhanced create_new with metadata
book = LocalBook.create_new(
    "my-data",
    "v1.0.0",
    edition=1,
    license="MIT",
    private=False,
    metadata={"author": "..."},
    local_bookshelf=path
)
book.add_timeseries("emissions", data)

# New publish method
book.publish()  # or publish(book)
```

**Pros:** Minimal new code, leverages existing patterns
**Cons:** Still somewhat verbose, no source file management

### Option B: BookBuilder Class

New class in `bookshelf-producer` that wraps LocalBook with a cleaner API:

```python
from bookshelf_producer import BookBuilder

book = BookBuilder("my-data", "v1.0.0", license="MIT")
book.add_timeseries("emissions", data)
book.add_dataframe("countries", df)
book.publish()

# With source file downloading
book = BookBuilder("my-data", "v1.0.0", license="MIT")
raw = book.download_source("https://example.com/data.csv", hash="sha256:...")
processed = transform(raw)
book.add_timeseries("processed", processed)
book.publish()
```

**Pros:** Clean entry point, can add conveniences (source downloading, validation)
**Cons:** New abstraction to maintain, potential overlap with LocalBook

### Option C: Both

- Enhance LocalBook with `publish()` and extended `create_new()` (Option A)
- Add BookBuilder as a convenience layer in producer package (Option B)
- Keep notebooks as a third path for those who prefer them

This gives users three paths based on their needs:

1. **Notebooks** - interactive exploration, complex multi-step processing
2. **BookBuilder** - scripts, CI/CD, straightforward publishing
3. **LocalBook directly** - maximum control, library authors

## Questions to Resolve

- Should `publish()` live on LocalBook (core package) or only in producer package?
  - This is less of an issue when we get an API because fetching/publishing are just an SDK request
- Do we want to deprecate notebooks eventually, or keep them as a first-class option?
- Should there be a CLI command for simple publishing without notebooks? (`bookshelf publish-file data.csv --name my-data --version v1.0.0`)
- Do we need an explict "register" step for a book
