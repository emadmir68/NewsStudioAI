from fastapi import HTTPException
import pytest
import app


def test_one_heavy_job_at_a_time():
    with app.JOBS_LOCK:
        original = dict(app.JOBS)
        app.JOBS.clear()
    try:
        first = app.new_job("animation_analysis", "abcd1234")
        with pytest.raises(HTTPException) as exc:
            app.new_job("animation_tts", "1234abcd")
        assert exc.value.status_code == 409
        app.set_job(first, status="completed")
        second = app.new_job("animation_tts", "1234abcd")
        assert second != first
    finally:
        with app.JOBS_LOCK:
            app.JOBS.clear()
            app.JOBS.update(original)


def test_memory_gate_prevents_low_memory_jobs(monkeypatch):
    monkeypatch.setattr(app, "available_ram_gb", lambda: 3.1)
    with pytest.raises(HTTPException) as exc:
        app.assert_memory_budget()
    assert exc.value.status_code == 503


def test_cancelled_job_state_is_not_overwritten():
    with app.JOBS_LOCK:
        original = dict(app.JOBS)
        app.JOBS.clear()
    try:
        jid = app.new_job("animation_analysis", "abcdef12")
        with app.JOBS_LOCK:
            app.JOBS[jid]["status"] = "cancelled"
        app.set_job(jid, status="completed", progress=100)
        assert app.get_job(jid)["status"] == "cancelled"
        with pytest.raises(RuntimeError):
            app.check_not_cancelled(jid)
    finally:
        with app.JOBS_LOCK:
            app.JOBS.clear()
            app.JOBS.update(original)
