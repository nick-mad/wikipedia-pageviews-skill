import json
import sqlite3
from pathlib import Path

import pytest

from wpv.http import Client

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def offline_client(tmp_path):
    """Client that serves recorded API responses and refuses network access."""
    db_path = tmp_path / "cache.sqlite"
    Client(db_path)  # creates the schema
    db = sqlite3.connect(db_path)
    for f in FIXTURES.glob("*.json"):
        for r in json.loads(f.read_text()):
            db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, 0, NULL)",
                       (r["url"], r["status"], json.dumps(r["body"], ensure_ascii=False)))
    db.commit()
    return Client(db_path, offline=True)
