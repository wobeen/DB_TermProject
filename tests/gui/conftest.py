import pytest

from tests.gui.career_synth import build_career


@pytest.fixture()
def career_path(tmp_path):
    path = tmp_path / "career.sqlite"
    build_career(path).close()
    return path


@pytest.fixture()
def career_conn(career_path):
    from scouting.db import connect

    conn = connect(career_path)
    yield conn
    conn.close()
