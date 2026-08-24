# bookshelf._cli

| Sub-package                           | Description                                                                                    |
| ------------------------------------- | ---------------------------------------------------------------------------------------------- |
| [__main__][bookshelf._cli.__main__]   | ``python -m bookshelf._cli`` entry point.                                                      |
| [_address][bookshelf._cli._address]   | The one-string address grammar: ``volume[@version[_eNNN]][/entry]``.                           |
| [_runtime][bookshelf._cli._runtime]   | Shared CLI plumbing: exit codes, the output contract, and error mapping.                       |
| [auth][bookshelf._cli.auth]           | ``bookshelf auth`` commands over two identity systems.                                         |
| [cache][bookshelf._cli.cache]         | ``bookshelf cache`` commands over the content cache the SDK fills.                             |
| [discovery][bookshelf._cli.discovery] | ``bookshelf search`` and ``bookshelf show``: what exists, and what one address is.             |
| [producer][bookshelf._cli.producer]   | ``bookshelf record``, ``bookshelf validate``, ``bookshelf publish`` and ``bookshelf discard``. |
| [volume][bookshelf._cli.volume]       | ``bookshelf volume``: the collection lifecycle a first publish needs.                          |

::: bookshelf._cli