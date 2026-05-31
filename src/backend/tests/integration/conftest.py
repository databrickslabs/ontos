"""Wire integration tests under backend/tests/ into the main app test harness."""
import sys
from pathlib import Path

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

pytest_plugins = ["tests.conftest"]
