from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as news_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "workspace"
    projects = workspace / "projects"
    workspace.mkdir(parents=True)
    projects.mkdir()
    monkeypatch.setattr(news_app, "WORKSPACE", workspace)
    monkeypatch.setattr(news_app, "PROJECTS_DIR", projects)
    monkeypatch.setattr(news_app, "AUTH_DB", workspace / "auth.sqlite3")
    news_app.init_db()
    with TestClient(news_app.app) as test_client:
        yield test_client


def create_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={"username": "adminuser", "password": "Strong-test-password-123"},
    )
    assert response.status_code == 200, response.text


def make_test_video(path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is not available")
    audio = r"aevalsrc=exprs=if(between(t\,2\,4)\,0\,0.2*sin(2*PI*440*t)):s=48000:d=6"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6",
            "-f", "lavfi", "-i", audio,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        check=True,
    )


def test_authentication_and_access_control(client: TestClient):
    assert client.get("/api/projects").status_code == 401
    create_admin(client)
    assert client.get("/api/auth/status").json()["authenticated"] is True
    assert client.get("/api/projects").status_code == 200

    response = client.post(
        "/api/users",
        json={"username": "reviewer1", "password": "Strong-review-password-123", "role": "reviewer"},
    )
    assert response.status_code == 200, response.text
    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": "reviewer1", "password": "Strong-review-password-123"},
    )
    assert login.status_code == 200, login.text
    assert client.post("/api/projects", json={"title": "غیرمجاز"}).status_code == 403
    assert client.get("/api/users").status_code == 403


def test_project_upload_silence_render_and_srt(client: TestClient, tmp_path: Path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe are required for media integration tests")
    create_admin(client)

    created = client.post("/api/projects", json={"title": "آزمون تدوین خبری"})
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    video = tmp_path / "source.mp4"
    make_test_video(video)
    with video.open("rb") as source:
        uploaded = client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": ("source.mp4", source, "video/mp4")},
        )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["source"]["duration"] == pytest.approx(6, abs=0.1)
    assert uploaded.json()["source"]["has_audio"] is True

    music = tmp_path / "music.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-q:a", "5", str(music)],
        check=True,
    )
    with music.open("rb") as music_file:
        music_upload = client.post(f"/api/projects/{project_id}/music", files={"file": ("music.mp3", music_file, "audio/mpeg")})
    assert music_upload.status_code == 200, music_upload.text

    logo = tmp_path / "logo.png"
    Image.new("RGBA", (160, 80), (30, 110, 150, 255)).save(logo)
    with logo.open("rb") as logo_file:
        logo_upload = client.post(f"/api/projects/{project_id}/logo", files={"file": ("logo.png", logo_file, "image/png")})
    assert logo_upload.status_code == 200, logo_upload.text

    updated = client.put(
        f"/api/projects/{project_id}",
        json={
            "headline": "تیتر آزمایشی",
            "profile": "vertical",
            "clips": [{"start": 0, "end": 6}],
            "subtitles": [{"start": 0.2, "end": 1.8, "text": "سلام، آزمون زیرنویس فارسی"}],
            "graphics": {
                "headline": "خبر آزمایشی",
                "lower_name": "خبرنگار",
                "lower_role": "گزارشگر",
                "ticker": "آخرین خبرها",
                "breaking": True,
                "show_logo": True,
            },
            "audio_settings": {"denoise": True, "music_duck": True, "music_volume": 0.12},
        },
    )
    assert updated.status_code == 200, updated.text

    silence = client.post(f"/api/projects/{project_id}/detect-silence?noise_db=-32&min_duration=0.6")
    assert silence.status_code == 200, silence.text
    silence_job = client.get(f"/api/jobs/{silence.json()['job_id']}").json()
    assert silence_job["status"] == "completed", silence_job
    assert len(silence_job["result"]["silences"]) >= 1

    applied = client.post(f"/api/projects/{project_id}/apply-silence-cuts")
    assert applied.status_code == 200, applied.text
    assert len(applied.json()["clips"]) >= 1

    srt = client.get(f"/api/projects/{project_id}/srt")
    assert srt.status_code == 200
    assert "سلام" in srt.content.decode("utf-8-sig")

    expected_sizes = {"vertical": (1080, 1920), "horizontal": (1920, 1080), "square": (1080, 1080)}
    for profile, expected_size in expected_sizes.items():
        render = client.post(f"/api/projects/{project_id}/render?profile={profile}")
        assert render.status_code == 200, render.text
        job = client.get(f"/api/jobs/{render.json()['job_id']}").json()
        assert job["status"] == "completed", job
        output = client.get(job["result"]["url"])
        assert output.status_code == 200
        assert len(output.content) > 20_000
        saved_output = tmp_path / f"{profile}.mp4"
        saved_output.write_bytes(output.content)
        assert news_app.probe(saved_output)["width"] == expected_size[0]
        assert news_app.probe(saved_output)["height"] == expected_size[1]


def test_invalid_inputs_are_rejected(client: TestClient):
    create_admin(client)
    assert client.post(
        "/api/users",
        json={"username": "x", "password": "short", "role": "admin"},
    ).status_code == 400
    assert client.post(
        "/api/projects/invalid-id/apply-silence-cuts"
    ).status_code == 404
