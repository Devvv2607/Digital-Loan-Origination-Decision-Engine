"""Check docs/API.md against the app's generated OpenAPI spec (method + path, both directions).

Usage (repo root): backend/.venv/Scripts/python scripts/check_api_docs.py
Exits non-zero if an endpoint is in one but not the other. No database is needed.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
for k, v in {"DATABASE_URL": "postgresql+psycopg://x:y@localhost:1/none", "JWT_SECRET": "x" * 40,
             "PII_HASH_KEY": "y" * 20, "ADMIN_USERNAME": "a", "ADMIN_PASSWORD": "z" * 10}.items():
    os.environ.setdefault(k, v)

from app.core.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402

spec = create_app(load_settings(_env_file=None)).openapi()
actual = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}

doc = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
documented = set()
for line in doc.splitlines():
    if line.startswith("### "):
        for m, p in re.findall(r"`(GET|HEAD|POST|PUT|PATCH|DELETE) (/[^`\s]*)`", line):
            documented.add((m, p))

missing, extra = sorted(actual - documented), sorted(documented - actual)
print(f"OpenAPI: {len(actual)} endpoints; API.md: {len(documented)} documented.")
for m, p in missing:
    print(f"  NOT DOCUMENTED  {m} {p}")
for m, p in extra:
    print(f"  NOT IN OPENAPI  {m} {p}")
sys.exit(1 if missing or extra else 0)
