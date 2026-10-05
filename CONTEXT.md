# Bookshelf SDK

The Python SDK for the Bookshelf Platform, Climate Resource's catalogue of curated climate datasets.

## Language

### Catalogue

**Volume**:
The long-lived, citable collection that releases belong to.

**Book**:
One immutable release within a Volume, versioned `{version}_e{edition:03}`.
_Avoid_: dataset, release

**Entry**:
A named file inside a Book.

**Resource**:
The bytes behind an Entry, or an `external_uri` pointer, carrying a permanent `tracking_id`.

### Credentials

**Credential store**:
Where stored logins live, one per deployment,
and the rule for which deployment is the default.
Has a file adapter for real use and an in-memory adapter for tests.
_Avoid_: credentials file (that is one adapter), keychain

**Stored login**:
One record in the Credential store,
for a WorkOS user on one deployment.

**Resolved credential**:
The credential one walk of the resolution chain chose for a deployment.
Callers ask it for requests' auth, a printable token, or a description,
and never branch on where it came from.
_Avoid_: ambient auth, credential source (that is one of its attributes)

**Rotation**:
Replacing a Stored login's secrets after a refresh.
It never changes which deployment is the default.

## Relationships

- A **Volume** holds many **Books**.
- A **Book** holds many **Entries**, and an **Entry** points at one **Resource**.
- A **Resolved credential** is built from the environment,
  or from one **Stored login** in a **Credential store**.
- A **Rotation** rewrites the **Stored login** a **Resolved credential** was built from.
