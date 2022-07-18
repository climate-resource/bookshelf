from bookshelf.notebook import run_notebook

book = run_notebook("example", force=True)

assert book.version
