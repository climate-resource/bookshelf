# The bundle format

A bundle is a directory holding a set of scientific outputs
together with a description of the run that produced them.
It is self-contained and does not require credentials or network access.

A project that keeps its own outputs on its own disk can write a bundle
and get a reviewable, diffable, content-addressed record of what was produced and what it came from.
Generally these bundles are then published to the Bookshelf platform,
but they could also be shared via other means.

This page specifies what is written to disk.
It is written so that an implementation in another language can produce and read bundles
without reading the Python that implements this one.

The format in force is manifest schema version **1.0**.

## Bundle directory

```text
bundle/
  manifest.lock
  resources/
    7198966a1a10c93fe40255d2c8e49b750e2cc7d3c9f56e4d06ac7e595e9afaa0.parquet
```

- `manifest.lock` is a YAML document that describes the bundle and its contents.
- `resources/` holds the bytes of every **managed** resource, keyed on content.

The filenames of the resources are derived from their hash and type:

- Take the recorded `hash`, which is always `sha256:` followed by exactly 64 lowercase hex characters.
- Drop the `sha256:` prefix.
  The 64 hex characters are the file's stem.
- The extension is `parquet` when the resource `type` is `timeseries` or `tabular`, and `bin` otherwise.

So a `timeseries` resource with hash `sha256:7198...faa0` is stored at
`resources/7198...faa0.parquet`.

The directory is content addressed,
so two resources with identical bytes and the same extension share one file.
The `manifest.lock` shall not refer to any files outside of the `resources/` directory,
in order to make the bundle portable.
Readers should ignore additional resources not included in the manifest.

## The manifest

`manifest.lock` is a mapping with four keys at the top level.

| Field            | Required                      | Meaning                                             |
| ---------------- | ----------------------------- | --------------------------------------------------- |
| `schema_version` | optional, defaults to `"1.0"` | the manifest schema this bundle was written against |
| `resources`      | optional, defaults to `[]`    | one record per registered resource                  |
| `activity`       | optional                      | a description of the run that produced the outputs  |
| `book`           | optional                      | the pre-edition framing of a book to publish        |

A bundle carrying only `resources` is valid.
Each of `activity` and `book` is additive.

### A resource record

Every entry in `resources` has these fields.

| Field          | Required     | Type                        | Default   | Meaning                                                                 |
| -------------- | ------------ | --------------------------- | --------- | ----------------------------------------------------------------------- |
| `tracking_id`  | required     | UUID                        |           | the identity of this resource within the bundle                         |
| `hash`         | required     | `sha256:<64 lowercase hex>` |           | the content hash, and the replay idempotency key                        |
| `type`         | required     | string                      |           | what sort of resource this is, see below                                |
| `kind`         | optional     | `managed` or `pointer`      | `managed` | which of the two variants this record is                                |
| `logical_key`  | optional     | string                      | absent    | the stable name lineage refers to this resource by                      |
| `format`       | optional     | string                      | absent    | the declared storage format, absent when it is not known                |
| `visibility`   | optional     | `hidden`, `org` or `public` | `hidden`  | the tier this resource records as                                       |
| `tags`         | optional     | list of strings             | `[]`      | free-form labels                                                        |
| `metadata`     | optional     | mapping                     | `{}`      | free-form metadata                                                      |
| `dedupe`       | optional     | boolean                     | `true`    | whether byte-identical resources may collapse to one canonical resource |
| `size`         | managed only | integer                     | absent    | the byte length of the stored bytes                                     |
| `external_uri` | pointer only | string                      | absent    | the external target                                                     |
| `generated`    | optional     | boolean                     | `false`   | whether an activity produced this resource                              |
| `used`         | optional     | list of references          | `[]`      | what this resource was derived from                                     |

The `type` values currently in use are:

- `timeseries`
- `tabular`
- `geospatial`
- `document`
- `binary`

The field is a plain string and the set is not closed,
so a reader must carry a type it does not recognise rather than refuse the bundle.
Only `timeseries` and `tabular` change how a byte file is named.

### `managed` versus `pointer`

`kind` is the discriminator between the two variants.
This allows referencing files that are stored elsewhere.

- `managed` means the bytes belong to the bundle.
  The record carries `size`, and `resources/<hex>.<ext>` holds bytes that hash to `hash`.
- `pointer` means the bytes stay where they are.
  The record carries `external_uri` and no `size`, and there is no byte file.
  A pointer says "this resource exists at that URI, and nothing may re-host it".

A reader must branch on `kind` and never infer the variant from a missing field.

A pointer still carries a `hash`, so lineage and identity work the same for both variants.
When the producer knows the external content's digest, it records it.
When it does not, the hash is synthesised so that a hashless pointer still has a stable identity:

- Build the mapping `{"type": <type>, "logical_key": <logical_key or "">, "locations": [["external", <external_uri>]]}`.
- Serialise it as JSON with sorted keys and `,` and `:` separators and no whitespace.
- The hash is `sha256:` followed by the hex digest of those UTF-8 bytes.

Every implementation must synthesise it the same way, because the identity of the pointer depends on it.

### Lineage

Lineage is expressed on the resource records, not as a separate graph.

- `generated: true` marks a resource as an output of the recorded activity.
- `used` lists what that output was derived from.

Each entry in `used` carries **exactly one** of two coordinates:

```yaml
used:
  - tracking_id: 0197a000-0000-7000-8000-00000000b001
  - logical_key: upstream/emissions
```

An entry with both, or with neither, is invalid.

References are recorded verbatim and are not resolved again later.
A reference by `logical_key` stays a reference by `logical_key`.
Whatever consumes the bundle mints exactly the edges the run expressed,
so lineage cannot drift between what the code did and what was recorded.

Inputs accumulate within a run.
A resource records the inputs known at the moment it was registered,
so a later output can cite more than an earlier one and never rewrites what the earlier one recorded.

### The activity envelope

The optional `activity` describes the run that produced the bundle.

| Field         | Required                   | Meaning                                                               |
| ------------- | -------------------------- | --------------------------------------------------------------------- |
| `activity_id` | required                   | UUID minted by the producer, stable across replays of the same bundle |
| `kind`        | required                   | what sort of run this was, for instance `build`                       |
| `code_ref`    | required                   | the code that ran, conventionally `<git remote>@<sha>`                |
| `config_hash` | required                   | a `sha256:<hex>` digest identifying the run's configuration           |
| `parameters`  | optional, defaults to `{}` | the parameters the run was given                                      |
| `runner`      | optional                   | what executed the run                                                 |

`config_hash` is what says two runs were configured the same way.
A producer that has a better digest records it.
Otherwise it is the digest of the canonical JSON of `parameters`.

A bundle records **one** activity.
Recording a second envelope that differs in any field is an error.
Recording an identical one again is not.

The envelope carries no start or end time and no duration.
Nothing in a bundle is a timestamp (see [Determinism](#determinism)).

### The book framing

`book` frames a book to draft and publish.
This field is specific to the Bookshelf and is optional.

| Field             | Required | Default  | Meaning                                                                          |
| ----------------- | -------- | -------- | -------------------------------------------------------------------------------- |
| `volume`          | required |          | the volume the book belongs to, referenced by name and never created by a bundle |
| `version`         | required |          | the consumer-facing data version                                                 |
| `visibility`      | optional | `hidden` | the tier of the book                                                             |
| `license`         | optional | absent   | the SPDX licence                                                                 |
| `authors`         | optional | `[]`     | recorded for provenance only                                                     |
| `description`     | optional | absent   | free prose                                                                       |
| `citation_doi`    | optional | absent   | a DOI for the dataset                                                            |
| `metadata`        | optional | `{}`     | free-form metadata                                                               |
| `data_dictionary` | optional | `[]`     | column-level descriptions                                                        |
| `entries`         | optional | `[]`     | the book's membership                                                            |
| `published`       | optional | `false`  | whether the book should be published, or left a draft                            |

Each entry in `entries` is a pair:

| Field          | Required | Meaning                                            |
| -------------- | -------- | -------------------------------------------------- |
| `name_in_book` | required | the stable name the resource takes inside the book |
| `tracking_id`  | required | a resource recorded in this same manifest          |

An entry must reference a resource recorded in the same manifest,
which is what keeps a bundle self-contained.
`name_in_book` is unique within a book.
A writer enforces both when it appends an entry.
Validation checks the reference and not the uniqueness,
so an implementation that reads a hand-edited manifest should check the names itself.

## Determinism

The manifest is written deterministically.
The same content produces byte-identical output on any machine, on any run.

- Every mapping is sorted by key, recursively.
  List order is preserved as recorded.
- Fields with no value are omitted rather than written as null.
- Newlines are LF, and the encoding is UTF-8, whatever the platform.
- Strings are written on one line, up to a bound of 10000 characters.
- Nothing is a timestamp, a hostname, a path from the producing machine, or a random id minted at write time.

This is what makes a bundle reviewable.
Re-running a build that produced the same outputs produces the same manifest,
so a diff shows what actually changed rather than the noise of a fresh run.
It also means a bundle can be committed to a repository and reviewed in a pull request
before anything is published anywhere.

## Versioning

`schema_version` is `<major>.<minor>`.
A reader models one major version, and this specification describes major 1.

- A **newer minor** loads.
  Minor changes are additive, and a reader ignores fields it does not model.
  An older reader therefore reads a newer bundle by dropping what it cannot understand.
- A **newer major** is refused.
  A reader must raise rather than interpret it,
  because a major change means a field it does model may now mean something else.
  Reading it anyway would silently drop meaning.
- A `schema_version` that is not a string, or whose major part is not an integer, is refused.
- An absent `schema_version` is read as the current version.

Tolerance is one-directional by design.

## Validation

These are the rules an implementation checks to decide that a bundle is a **replayable published book**.
A replayable book contains all the required information to later be streamed to the Bookshelf API.

1. The manifest records a `book`.
2. That book has `published: true`.
3. That book has at least one entry.
4. Every entry's `tracking_id` matches a resource recorded in the same manifest.
5. Every resource with `kind: managed` has a byte file, and those bytes hash to the recorded `hash`.
   A resource whose `hash` is not canonical fails here, because it names no byte file.

Rule 5 re-hashes rather than trusting the manifest.
A bundle edited between being recorded and being used is refused,
so what is published is what the reviewer saw.

A bundle that fails any of these is still a bundle.
A resources-only bundle, or one whose book is a draft, is a perfectly valid artefact.
It is just not a replayable published book,
so a consumer that is about to publish refuses it and says which rule failed.

Pointers are not fetched during validation.
Nothing checks that an `external_uri` resolves, and nothing verifies an external digest.
A pointer is a claim about somewhere else,
and validating it would need the network that the format is designed to avoid.

## What a bundle does not carry

- **The edition.**
  A bundle is pre-edition.
  The identity of a published edition is assigned by the server when the bundle is replayed,
  and it is the Nth reprocessing of that `(volume, version)` and nothing more.
  An offline consumer must not synthesise an edition or treat `version` as one.
  What identifies a generation of processing is the activity's `code_ref` and `config_hash`.
- **A derived seal.**
  Replay keys a draft on a hash computed over the book's licence, visibility and sorted membership.
  That value is derived from the manifest when it is needed.
  It is not stored in the bundle.
- **Timestamps and machine state.**
  See [Determinism](#determinism).
- **The volume.**
  A bundle references a volume by name and never creates one.
- **Anything about a server.**
  No URLs, no organisation, no credentials, no account.
  A bundle names its content and its provenance, and nothing about where it might end up.

## A worked example

A complete bundle with one pointer, one managed resource derived from it,
an activity envelope and book framing.

```text
bundle/
  manifest.lock
  resources/
    7198966a1a10c93fe40255d2c8e49b750e2cc7d3c9f56e4d06ac7e595e9afaa0.parquet
```

```yaml
activity:
  activity_id: 0197a000-0000-7000-8000-00000000a001
  code_ref: git@github.com:example/example-emissions@0f7c1e2
  config_hash: sha256:2078d1b688f90612b09a8b97cf0ef12c6f5e915ebe8f7bf252a82b76a321e5c2
  kind: build
  parameters:
    upstream_version: v1.0.0
  runner: python-3.13
book:
  authors:
  - email: ada@example.com
    name: Ada Lovelace
  data_dictionary: []
  description: A worked example bundle.
  entries:
  - name_in_book: upstream.csv
    tracking_id: 0197a000-0000-7000-8000-00000000b001
  - name_in_book: emissions.parquet
    tracking_id: 0197a000-0000-7000-8000-00000000b002
  license: CC-BY-4.0
  metadata: {}
  published: true
  version: v1.0.0
  visibility: public
  volume: example-emissions
resources:
- dedupe: true
  external_uri: https://example.org/upstream/emissions-v1.0.0.csv
  generated: false
  hash: sha256:c6dd00dc24e5ddcf21081c662e8264bbc0cf7d10986181f961545eaef0e4051c
  kind: pointer
  logical_key: upstream/emissions
  metadata: {}
  tags: []
  tracking_id: 0197a000-0000-7000-8000-00000000b001
  type: tabular
  used: []
  visibility: public
- dedupe: true
  format: parquet
  generated: true
  hash: sha256:7198966a1a10c93fe40255d2c8e49b750e2cc7d3c9f56e4d06ac7e595e9afaa0
  kind: managed
  logical_key: emissions/co2
  metadata: {}
  size: 1396
  tags: []
  tracking_id: 0197a000-0000-7000-8000-00000000b002
  type: timeseries
  used:
  - tracking_id: 0197a000-0000-7000-8000-00000000b001
  visibility: public
schema_version: '1.0'
```

Reading it back:

- The pointer carries no bytes and no `size`, so `resources/` holds one file, not two.
- Its hash was synthesised from its type, logical key and URI,
  because the producer did not know the upstream digest.
- The managed resource cites the pointer by `tracking_id`, which is the lineage edge.
- The book publishes both under names of its own choosing, and carries no edition.

## For a Python reader

`bookshelf.publisher.bundle` implements this format.
`Bundle.read`, `Bundle.validate` and `Bundle.read_validated` load and check a bundle directory,
and the `Bundle*` models mirror the manifest structure field for field.
`bookshelf.publisher.recording` writes bundles from a producer run,
and `bookshelf.publisher.replay` sends one to the platform.
