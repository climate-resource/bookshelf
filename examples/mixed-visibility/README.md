# `mixed-visibility`

A public book carrying one hidden resource.

The rule this example pins has three parts.

1. Precedence is the caller, then the book's `visibility`, then the default, and the default is `hidden`.
   The recipe states `hidden` under `defaults:` and `public` on the book, and the book's value wins.
2. The book's resolved tier becomes the default every resource it records afterwards takes,
   so declaring the book public is enough to publish public data.
   `by_region` and `world` name no tier and are public.
3. A registration passing its own `visibility=` narrows or widens that one resource, and nothing else.
   `working_set` is narrowed to `hidden` inside a `public` book, which is a deliberate act,
   and the book stays public.

`None` and `INHERIT` both mean the caller said nothing.
An empty string is invalid input to reject, never a signal to inherit the recipe's value.

`expected/v1.0.0/manifest.lock` is that rule written down:
the book public, `working_set` hidden, everything else public by inheritance.

```bash
bookshelf record --recipe examples/mixed-visibility/bookshelf.yaml --version v1.0.0 --bundle /tmp/mv
bookshelf validate /tmp/mv
```
