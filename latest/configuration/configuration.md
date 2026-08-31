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
- `BOOKSHELF_USE_KEYCHAIN` stores credentials in the OS keychain instead of the file.

## Where credentials are stored

`bookshelf auth login` writes its record to a `0600` file under the user config directory.

Set `BOOKSHELF_USE_KEYCHAIN=1` to put the secrets in the OS keychain instead,
leaving the file as the index that names them.
Switching the variable on or off does not move secrets already stored.
Run `bookshelf auth login` again to write them to their new home.

The default API URL is the production Bookshelf deployment.
Pass `base_url=` to `Bookshelf`, `AsyncBookshelf`, or `BookshelfClient`
when a particular deployment must be explicit.
