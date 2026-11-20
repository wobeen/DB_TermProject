import threading

from scouting.gui.app import BackgroundJobs
from tests.app.synth import new_db


class ImmediateRoot:
    def after(self, _delay, callback): callback()


def test_background_delivers_success_and_error(tmp_path):
    path = tmp_path / "job.sqlite"; conn = new_db(path); conn.close()
    statuses, results = [], []
    runner = BackgroundJobs(ImmediateRoot(), path, statuses.append)
    thread = runner.submit("테스트", lambda c: c.execute("SELECT 7").fetchone()[0], results.append)
    thread.join(5)
    assert results == [7]
    assert "완료" in statuses[-1]
    done = threading.Event()
    thread = runner.submit("실패", lambda _c: (_ for _ in ()).throw(ValueError("가짜 오류")),
                           on_error=lambda _e: done.set())
    thread.join(5)
    assert done.is_set()
    assert statuses[-1] == "오류: 가짜 오류"
