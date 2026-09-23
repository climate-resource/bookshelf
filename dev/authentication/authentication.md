# Authentication

Reading a public book needs no credential at all,
but the bookshelf does have some features that require authentication,
such reading private books, drafting a book, and publishing one.

This page covers the methods the SDK and the `bookshelf` CLI support,
which one to pick, and the order they are tried in.
The environment variables named here are described in full in [Configuration](configuration.md).

## Authentication methods

Pick the method that matches who is calling.

| Method                  | Who it is for                                | How to start                                               |
| ----------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| Anonymous               | anyone reading public books                  | nothing to do                                              |
| User login, browser     | a person on a machine with a browser         | `bookshelf auth login`                                     |
| User login, device code | a person on a headless machine or over SSH   | `bookshelf auth login --no-browser`                        |
| Anonymous agent         | a program that only reads public books       | `bookshelf auth login --agent`                             |
| Claimed agent           | a program acting for a person's organisation | `bookshelf auth login --agent --claim --email you@org.com` |
| Bearer token            | a script handed a token by something else    | `$BOOKSHELF_TOKEN`, or `Bookshelf(auth="...")`             |
| GitHub Actions          | a workflow reading its organisation's books  | `$BOOKSHELF_AUTH=github-actions`                           |

## Log in as a person

`bookshelf auth login` starts an interactive login and stores the result,
so you do this once per machine rather than once per session.

On a machine with a browser it opens one, you sign in, and the credential comes back to the CLI.

On a machine with no browser it uses the device authorization flow instead,
which moves the sign-in to a machine that has one.
The CLI prints a short code and a URL:

```text
Your code:  WDJB-MJHT
Visit       <the verification URL the issuer returns>
```

1. The CLI prints the code and starts waiting.
2. You open that URL on any other machine, on a phone if that is what is to hand.
3. You sign in and confirm the code shown there matches the one the CLI printed.
4. The CLI notices the approval and stores the credential.

The code expires after a few minutes. Run the command again for a fresh one.

A notebook, an SSH session and a terminal with no usable browser all take this path without being asked.
Pass `--no-browser` to force it.

The stored credential is periodically renewed
You may periodically need to rerun `bookshelf auth login` to generate a new long-lived token.

## Register an agent identity

An agent identity is for a program acting on its own rather than on behalf of a person at a keyboard.

`bookshelf auth login --agent --claim --email you@org.com` registers the identity
and then asks a named person to vouch for it.
`--email` is the address that person signs in with.

1. The CLI registers the identity and prints a code and a URL, then starts waiting.
2. The named person opens the URL, signs in, and sees which agent is asking.
3. They approve it, or they do not.
4. On approval the CLI stores the identity, now bound to that person's organisation.

The code expires after a few minutes, and the CLI says how long is left while it waits.

A claimed identity reads that organisation's private books and may write.
The claim ceremony registers a new identity rather than upgrading an existing one,
so an anonymous agent that later needs private access runs the claim command and gets a second identity.

## Use a token directly

`$BOOKSHELF_TOKEN` is sent as a bearer token exactly as given.
Nothing refreshes it, so a short-lived token will expire part way through a long run.
`bookshelf auth token` prints a current token from a session that is already logged in,
which is the usual way to get one.

In Python, `auth=` on `Bookshelf`, `AsyncBookshelf` and `BookshelfClient` overrides everything else.
It takes a bearer token string or a credential provider.

```python
from bookshelf import Bookshelf

with Bookshelf(auth="...") as bs:
    ...
```

`auth=None` stays unauthenticated even when a stored login exists,
which is the way to guarantee a client only ever sees public data.

## Read from GitHub Actions

A workflow job reads its organisation's books with the token GitHub mints for it,
so the repository holds no Bookshelf secret.
The repository has to be enrolled,
which is what the Bookshelf GitHub App installation does.

Give the job the permission and set the opt-in variable:

```yaml
permissions:
  id-token: write
env:
  BOOKSHELF_AUTH: github-actions
```

The opt-in is deliberate.
A job that holds `id-token: write` for something else never sends its token to Bookshelf
unless the workflow explicitly opts in.

The token is read-only, and every write is refused,
so a job that publishes still needs a credential of its own.
Tokens last minutes, so the client mints a fresh one and replaces it whenever the API refuses one.

## Credential precedence

With `auth=` omitted, the client walks this chain and takes the first step that answers.

1. `$BOOKSHELF_TOKEN`
2. the job's GitHub Actions OIDC token, when `$BOOKSHELF_AUTH` is `github-actions`
3. `$BOOKSHELF_CLIENT_ID` with `$BOOKSHELF_CLIENT_SECRET`
4. the stored identity that is active for that deployment
5. unauthenticated

Passing `auth=` skips the chain entirely.
Any credentials are scoped to a single bookshelf deployment.

`bookshelf auth whoami` reports the current identity.
In Python, `Bookshelf().ensure_authenticated()` confirms the API accepts the credential,
and attempts to prompt for authentication if you are not logged in.

## Manage stored identities

One machine can hold several identities, and one is active per deployment.

- `bookshelf auth list` shows every stored identity, marking the active one per deployment.
  `--json` emits one object per identity.
- `bookshelf auth switch <identity>` makes a different stored identity active
  without authenticating again.
  Take the name from `auth list`, and pass `--api-url` when the same name exists on two deployments.
- `bookshelf auth token` prints the current access token and nothing else,
  refreshing it first when one is due.
- `bookshelf auth logout` revokes the credential and clears local state.
  `--all` covers every deployment, and `--no-revoke` clears locally without telling the server.

## Where credentials are stored

Credentials live in `credentials.json` under the user config directory,
which is `~/.config/bookshelf` on Linux and `~/Library/Application Support/bookshelf` on macOS.
The file is written `0600`.

It holds every stored identity and which one is active for each deployment,
so `auth switch` is a local change.
