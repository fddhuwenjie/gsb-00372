"""Root conftest: make the backend package importable without PYTHONPATH.

Paths are derived from this file's location, so the suite runs from a fresh
checkout on any machine: ``python -m pytest`` at the repository root.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, 'backend')

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
