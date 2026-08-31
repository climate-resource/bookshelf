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

`bookshelf auth login` writes its record to a `0600` file
under the user config directory,
secrets included.
This is the same protection the AWS CLI gives `~/.aws/credentials`.

Set `BOOKSHELF_USE_KEYCHAIN=1` to put the secrets in the OS keychain instead,
leaving the file as the index that names them.

The keychain is not the default, because it cannot keep its promise for a library.
macOS binds a keychain item's access control list
to the designated requirement of the process that reads it.
An SDK installed from PyPI runs under whatever interpreter the user has,
and the common ones (uv, Homebrew, pyenv) are ad-hoc signed with no stable identity,
so the list pins to a code hash that changes on the next interpreter upgrade.
The result is an unlock prompt on every command that "always allow" cannot silence.
Turn the keychain on where the interpreter is properly signed,
or on a platform whose backend is a real secret service.

Switching the variable on or off does not move secrets already stored.
Run `bookshelf auth login` again to write them to their new home.
`bookshelf auth list` names any deployment left behind, and logout clears both homes either way.

The default API URL is the production Bookshelf deployment.
Pass `base_url=` to `Bookshelf`,
`AsyncBookshelf`,
or `BookshelfClient`
when a particular deployment must be explicit.
