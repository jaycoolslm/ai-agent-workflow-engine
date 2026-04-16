"""Pytest configuration — adds the project root to sys.path so tests can
import top-level packages (storage, runtime, evaluation, harness, etc.)
without installing the project as a package."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
