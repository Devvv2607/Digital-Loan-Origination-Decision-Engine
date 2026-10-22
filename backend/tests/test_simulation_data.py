"""The committed synthetic dataset is reproducible and tied to a fixed as-of date, not today."""

import importlib.util
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _generator():
    spec = importlib.util.spec_from_file_location("generate_applications", ROOT / "scripts" / "generate_applications.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_uses_a_fixed_as_of_date_and_reproduces_the_committed_file():
    gen = _generator()
    assert gen.AS_OF == date(2026, 10, 22)
    committed = json.loads((ROOT / "reports" / "synthetic_applications.json").read_text(encoding="utf-8"))
    assert committed["metadata"]["as_of_date"] == gen.AS_OF.isoformat()
    assert gen.generate(gen.DEFAULT_SEED, gen.AS_OF) == committed
