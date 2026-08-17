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

The format in force is manifest schema version **3.0**.

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

`manifest.lock` is a mapping with five keys at the top level.

| Field            | Required                      | Meaning                                             |
| ---------------- | ----------------------------- | --------------------------------------------------- |
| `schema_version` | always written                | the manifest schema this bundle was written against |
| `writer`         | optional                      | the library versions that wrote the resource bytes  |
| `resources`      | optional, defaults to `[]`    | one record per registered resource                  |
| `activity`       | optional                      | a description of the run that produced the outputs  |
| `book`           | optional                      | the pre-edition framing of a book to publish        |

A bundle carrying only `resources` is valid.
Each of `writer`, `activity` and `book` is additive.

### The writer header

`writer` records the versions of the libraries that produced the bytes under `resources/`.
It carries one field.

| Field     | Required | Type   | Meaning                                    |
| --------- | -------- | ------ | ------------------------------------------ |
| `pyarrow` | optional | string | the pyarrow that wrote the parquet bytes   |

Parquet output is not stable across pyarrow versions,
so the same frame written by two pyarrow versions has two content hashes.
Recording the version makes that difference explain itself
rather than surfacing as an unattributed change in the recorded hashes.

The whole block is absent when pyarrow was not installed on the machine that wrote the bundle.
It is also absent from any bundle written against schema `1.0`,
because the field did not exist then.

### A resource record

Every entry in `resources` has these fields.

| Field          | Required     | Type                        | Default   | Meaning                                                                 |
| -------------- | ------------ | --------------------------- | --------- | ----------------------------------------------------------------------- |
| `name`         | required     | string                      |           | the bundle-local name this resource is addressed by                     |
| `hash`         | required     | `sha256:<64 lowercase hex>` |           | the content hash, and the replay idempotency key                        |
| `type`         | required     | string                      |           | what sort of resource this is, see below                                |
| `kind`         | optional     | `managed` or `pointer`      | `managed` | which of the two variants this record is                                |
| `format`       | optional     | string                      | absent    | the declared storage format, absent when it is not known                |
| `visibility`   | optional     | `hidden`, `org` or `public` | `hidden`  | the tier this resource records as                                       |
| `tags`         | optional     | list of strings             | `[]`      | free-form labels                                                        |
| `metadata`     | optional     | mapping                     | `{}`      | free-form metadata                                                      |
| `dedupe`       | optional     | boolean                     | `true`    | whether byte-identical resources may collapse to one canonical resource |
| `size`         | managed only | integer                     | absent    | the byte length of the stored bytes                                     |
| `external_uri` | pointer only | string                      | absent    | the external target                                                     |
| `generated`    | optional     | boolean                     | `false`   | whether an activity produced this resource                              |
| `used`         | optional     | list of names               | `[]`      | what this resource was derived from                                     |

`name` is local to the bundle that registers it, and it carries no hierarchy.
It matches `^[a-z0-9][a-z0-9._-]{0,199}$`, it is unique within the manifest,
and it is the name the platform registers the resource under.
A resource that a book entry names takes that name inside the book too.

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

- Build the mapping `{"type": <type>, "locations": [["external", <external_uri>]]}`.
  The name is deliberately not part of the seed,
  so the same external pointer collides on the same canonical resource
  no matter what the producer named it.
- Serialise it as JSON with sorted keys and `,` and `:` separators and no whitespace.
- The hash is `sha256:` followed by the hex digest of those UTF-8 bytes.

Every implementation must synthesise it the same way, because the identity of the pointer depends on it.

### Lineage

Lineage is expressed on the resource records, not as a separate graph.

- `generated: true` marks a resource as an output of the recorded activity.
- `used` lists what that output was derived from.

`used` names the resources an output was derived from:

```yaml
used:
  - upstream-emissions
```

Each name must belong to a resource recorded **earlier** in the same `resources` list,
so an input is always registered before whatever consumes it.
A name the manifest does not carry is invalid.
The server resolves each name against the resources of that same replay and nothing else,
so the same bundle always resolves to the same inputs however often it is replayed.

Order is therefore part of the format rather than an accident of how the bundle was written.

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
| `authors`         | optional | `[]`     | the people credited with this version, sent on the replay                        |
| `discovery`       | optional | absent   | the editorial metadata baked onto this book, keyed by the recipe's field names   |
| `description`     | optional | absent   | free prose                                                                       |
| `metadata`        | optional | `{}`     | free-form metadata                                                               |
| `entries`         | optional | `[]`     | the book's membership                                                            |
| `published`       | optional | `false`  | whether the book should be published, or left a draft                            |
| `processing`      | optional | absent   | the `[code_ref, config_hash]` pairs of the runs that generated the book's members |

`discovery` and `authors` hold values the recipe has already resolved,
so the bundle records what will be published rather than what was declared.
Replay sends both,
which is how each book keeps its own copy of what was true when it was published.
Neither enters the seal the server computes.

`processing` is provenance, and it is not part of the seal.
It answers "which code produced this", and nothing more.
A rebuild whose code changed but whose data did not converges on the existing edition,
which is what [ADR 0006][adr-0006] settled.

[adr-0006]: https://github.com/climate-resource/bookshelf-platform/blob/main/docs/adr/0006-server-owns-edition-code-version-is-provenance.md
An absent `processing` states nothing, and `[]` states a book that no activity generated.
Replay does not send it, because the replay request carries the activity itself
and the server derives the book's fingerprint from that.
It is recorded so `bookshelf validate` reads as a complete account of the build.

Each entry in `entries` carries the membership and its own optional column descriptions:

| Field             | Required | Default | Meaning                                            |
| ----------------- | -------- | ------- | -------------------------------------------------- |
| `name`            | required |         | a resource recorded in this same manifest          |
| `data_dictionary` | optional | absent  | column-level descriptions that apply to this entry |

An absent `data_dictionary` leaves the entry's existing dictionary unchanged on replay.
An empty list explicitly clears it,
which is the declaration used for notebooks and rendered pages.

An entry must name a resource recorded in the same manifest,
which is what keeps a bundle self-contained.
The entry's name is the resource's name, and it is unique within a book,
because the platform registers a replayed resource under the name its entry takes.
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
A reader models one major version, and this specification describes major 3.

- A **newer minor** loads.
  Minor changes are additive, and a reader ignores fields it does not model.
  An older reader therefore reads a newer bundle by dropping what it cannot understand.
- A **newer major** is refused.
  A reader must raise rather than interpret it,
  because a major change means a field it does model may now mean something else.
  Reading it anyway would silently drop meaning.
- An **older major** is refused.
- A `schema_version` that is not a string, or whose major part is not an integer, is refused.
- An absent `schema_version` is read as the current version.

Tolerance is one-directional by design.

## Validation

These are the rules an implementation checks to decide that a bundle is a **replayable published book**.
A replayable book contains all the required information to later be streamed to the Bookshelf API.

1. The manifest records a `book`.
2. That book has `published: true`.
3. That book has at least one entry.
4. Every entry's `name` matches a resource recorded in the same manifest.
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
- **A seal.**
  The server computes the seal from the replay request alone,
  which is what makes two replays of one bundle converge on one edition.
  The client neither stores nor computes it.
- **Tracking ids.**
  The platform owns the mapping from a bundle-local name to the resource it registered,
  so nothing in a bundle names a row on a server.
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
  description: A worked example bundle.
  entries:
  - name: upstream-emissions
  - data_dictionary:
    - name: region
      role: dimension
      type: string
    name: emissions-co2
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
  metadata: {}
  name: upstream-emissions
  tags: []
  type: tabular
  used: []
  visibility: public
- dedupe: true
  format: parquet
  generated: true
  hash: sha256:7198966a1a10c93fe40255d2c8e49b750e2cc7d3c9f56e4d06ac7e595e9afaa0
  kind: managed
  metadata: {}
  name: emissions-co2
  size: 1396
  tags: []
  type: timeseries
  used:
  - upstream-emissions
  visibility: public
schema_version: '3.0'
writer:
  pyarrow: 23.0.0
```

Reading it back:

- The pointer carries no bytes and no `size`, so `resources/` holds one file, not two.
- Its hash was synthesised from its type and URI,
  because the producer did not know the upstream digest.
- The managed resource cites the pointer by name, which is the lineage edge,
  and the pointer is recorded before it, which is what makes that citation legal.
- The book publishes both under the names their resources carry, and carries no edition.

## For a Python reader

`bookshelf.publisher.bundle` implements this format.
`Bundle.read`, `Bundle.validate` and `Bundle.read_validated` load and check a bundle directory,
and the `Bundle*` models mirror the manifest structure field for field.
`bookshelf.publisher.recording` writes bundles from a producer run,
and `bookshelf.publisher.replay` sends one to the platform.
