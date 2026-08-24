# bookshelf.publisher

| Sub-package                                | Description                                                                   |
| ------------------------------------------ | ----------------------------------------------------------------------------- |
| [bundle][bookshelf.publisher.bundle]       | The bundle: an on-disk, replayable record of a run, using manifest schema v3. |
| [notebook][bookshelf.publisher.notebook]   | Notebook capture for a recorded build.                                        |
| [publish][bookshelf.publisher.publish]     | Decide what publishing a recorded bundle should do, and do it.                |
| [recipe][bookshelf.publisher.recipe]       | What a feedstock declares                                                     |
| [record][bookshelf.publisher.record]       | Driver that executes a standalone build file into a reviewable bundle.        |
| [recording][bookshelf.publisher.recording] | Bundle-backed adapter for the producer write surface.                         |
| [reference][bookshelf.publisher.reference] | The ``bookshelf://`` reference a recipe uses to build on published data.      |
| [replay][bookshelf.publisher.replay]       | Replay a recorded bundle through the platform's one-call replay endpoint.     |
| [resource][bookshelf.publisher.resource]   | Fetch, verify, cache and register the resources a version declares.           |

::: bookshelf.publisher