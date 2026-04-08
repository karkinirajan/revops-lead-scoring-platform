"""
pytest conftest — adds the repo root to sys.path so that
`workers.*` modules are importable from API tests.
"""
import os
import sys

# Repo root: apps/api/tests/../../.. = repo root
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
