# Makefile to help automate key steps

.DEFAULT_GOAL := help
# Will likely fail on Windows, but Makefiles are in general not Windows
# compatible so we're not too worried
TEMP_FILE := $(shell mktemp)

# Files that are formatted by Ruff
FILES_TO_FORMAT := src tests notebooks scripts docs/source/conf.py docs/source/notebooks/*.py


# some of our sources have to be downloaded from older servers, need
# a more relaxed openssl config
OPENSSL_CONF ?= .github/openssl.cnf
export OPENSSL_CONF

# A helper script to get short descriptions of each target in the Makefile
define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([\$$\(\)a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-30s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT


.PHONY: help
help:  ## print short description of each target
	@python3 -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

.PHONY: checks
checks:  ## run all the linting checks of the codebase
	@echo "=== pre-commit ==="; uv run pre-commit run --all-files || echo "--- pre-commit failed ---" >&2; \
		echo "=== mypy ==="; MYPYPATH=stubs uv run mypy src || echo "--- mypy failed ---" >&2; \
		echo "======"

.PHONY: ruff-fixes
ruff-fixes:  ## fix the code using ruff
    # format before and after checking so that the formatted stuff is checked and
    # the fixed stuff is formatted
	uv run ruff format $(FILES_TO_FORMAT)
	uv run ruff $(FILES_TO_FORMAT) --fix
	uv run ruff format $(FILES_TO_FORMAT)

.PHONY: test-producer
test-producer:  ## run the tests for the producer package
	uv run --package bookshelf_producer \
		pytest packages/bookshelf-producer \
		-r a -v --doctest-modules --cov=packages/bookshelf-producer/src

.PHONY: test-core
test-core:  ## run the tests for the core package
	uv run \
		pytest src tests \
		-r a -v --doctest-modules --cov=src

.PHONY: test
test: test-core test-producer  ## run the tests


# Note on code coverage and testing:
# You must specify cov=src as otherwise funny things happen when doctests are
# involved.
# If you want to debug what is going on with coverage, we have found
# that adding COVERAGE_DEBUG=trace to the front of the below command
# can be very helpful as it shows you if coverage is tracking the coverage
# of all of the expected files or not.
# We are sure that the coverage maintainers would appreciate a PR that improves
# the coverage handling when there are doctests and a `src` layout like ours.

.PHONY: docs
docs:  ## build the docs
	uv run --with bookshelf-producer mkdocs build

.PHONY: docs-strict
docs-strict: ## build the docs strictly (e.g. raise an error on warnings, this most closely mirrors what we do in the CI)
	uv run --with bookshelf-producer mkdocs build --strict

.PHONY: docs-serve
docs-serve: ## serve the docs locally
	uv run --with bookshelf-producer mkdocs serve

.PHONY: changelog-draft
changelog-draft:  ## compile a draft of the next changelog
	uv run towncrier build --draft

.PHONY: licence-check
licence-check:  ## Check that licences of the dependencies are suitable
	# Will likely fail on Windows, but Makefiles are in general not Windows
	# compatible so we're not too worried
	uv export --without=tests --without=docs --without=dev > $(TEMP_FILE)
	uv run liccheck -r $(TEMP_FILE) -R licence-check.txt
	rm -f $(TEMP_FILE)

.PHONY: virtual-environment
virtual-environment:  ## update virtual environment, create a new one if it doesn't already exist
	uv sync
	uv run pre-commit install
