import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import synth  # noqa: E402


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "t.sqlite"
    conn = synth.new_db(path)
    ids = synth.build_main(conn)
    conn.close()
    return path, ids


@pytest.fixture()
def env(db_path):
    from scouting.db import connect

    path, ids = db_path
    conn = connect(path)
    yield conn, ids
    conn.close()
