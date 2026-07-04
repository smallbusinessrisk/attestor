"""
pytest configuration.

attestor/__init__.py extends its own __path__ to include the repo root,
so attestor.core.* and attestor.adapters.* resolve correctly regardless of
which directory pytest adds to sys.path.

This conftest is intentionally minimal — the path logic lives in __init__.py.
"""
# No sys.path manipulation needed here; __init__.py handles it via __path__.
