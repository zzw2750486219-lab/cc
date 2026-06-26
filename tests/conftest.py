from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["WORKER_ENABLED"] = "0"

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_workspace(tmp_path):
    """Temporary workspace directory for tool tests."""
    return str(tmp_path)
