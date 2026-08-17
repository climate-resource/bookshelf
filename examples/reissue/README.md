# `reissue`

The same version, rebuilt with the processing changed and the data unchanged.

The server owns the edition, and a code version is provenance rather than identity.
Processing is therefore recorded in the manifest and never enters the seal,
which the SDK does not compute at all.
The consequence this example exists to demonstrate is that a rebuild whose code or parameters changed
but whose bytes did not converges on the existing edition rather than minting a new one.

Record it twice, changing only the build parameter:

```bash
bookshelf record --recipe examples/reissue/bookshelf.yaml --version v1.0.0 --bundle /tmp/reissue-a
bookshelf record --recipe examples/reissue/bookshelf.yaml --version v1.0.0 --bundle /tmp/reissue-b -p chunk_size=5
bookshelf validate /tmp/reissue-a
bookshelf validate /tmp/reissue-b
```

The two validations report different `processing` values,
because the activity's `config_hash` is over the parameters the build ran with.
Everything the seal covers is identical: the same resources, the same content hashes, the same entries.

`chunk_size` is a top-level assignment in the build file, because that is what `-p` replaces.
It changes how the input frame is walked and not how the numbers are added,
so the outputs are identical by construction rather than equal to within rounding.

The golden here is the run with the default parameter.
`packages/bookshelf/tests/test_examples.py` is where the two-run comparison is asserted,
because a golden holds one recording and this claim is about the difference between two.
