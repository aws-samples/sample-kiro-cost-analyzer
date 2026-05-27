"""Global pytest configuration.

Adds package roots to sys.path so tests use clean direct imports that
mirror what Lambda sees at runtime.

Lambda sees (via layer + CodeUri):
  /opt/python/shared/         → from shared.xxx
  /opt/python/git_shared/     → from git_shared.xxx
  /var/task/                   → handler code (handlers/, repository/, etc.)

This conftest replicates that by adding:
  layers/shared/  → shared, git_shared
  backend/        → repository, handlers, correlation_engine
  etl/            → processors, utils, prompt_categorizer, etc.
  project root    → backend.xxx, etl.xxx (package-qualified in tests)
"""
import sys
import os

_root = os.path.dirname(__file__)

_paths = [
    os.path.join(_root, "layers", "shared"),  # shared, git_shared
    os.path.join(_root, "backend"),           # repository, handlers, correlation_engine
    os.path.join(_root, "etl"),               # processors, utils, prompt_categorizer
    _root,                                    # backend.xxx, etl.xxx
]

for _path in _paths:
    if _path not in sys.path:
        sys.path.insert(0, _path)
