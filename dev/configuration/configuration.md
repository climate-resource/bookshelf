# Configuration

Constructor arguments take precedence over ambient configuration.
The SDK recognises these environment variables:

- `BOOKSHELF_URL` selects the API deployment.
  `BOOKSHELF_API_URL` is accepted as an alias.
- `BOOKSHELF_TOKEN` supplies a static bearer token.
- `BOOKSHELF_CLIENT_ID` and `BOOKSHELF_CLIENT_SECRET`
  enable OAuth client credentials.
  `BOOKSHELF_TOKEN_URL` must name the token endpoint.
- `BOOKSHELF_WORKOS_CLIENT_ID` configures interactive user login.
- `BOOKSHELF_WORKOS_BASE_URL` overrides the WorkOS API base URL.

When authentication is omitted,
the SDK resolves a static environment token first,
then client credentials,
then stored `bookshelf auth login` credentials.
Public reads remain available without authentication.

The default API URL is the production Bookshelf deployment.
Pass `base_url=` to `Bookshelf`,
`AsyncBookshelf`,
or `BookshelfClient`
when a particular deployment must be explicit.
