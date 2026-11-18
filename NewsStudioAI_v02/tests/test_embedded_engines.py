"""No-network tests for bundled engines and their installation layout."""
from pathlib import Path
import embedded_engines as engines


def test_missing_embedded_models_are_reported_without_installing(monkeypatch, tmp_path):
    monkeypatch.setattr(engines, "engine_root", lambda: tmp_path)
    assert not engines.vision_status()["available"]
    assert not engines.voice_status()["ready"]


def test_embedded_installation_detected(monkeypatch, tmp_path):
    monkeypatch.setattr(engines, "engine_root", lambda: tmp_path)
    (tmp_path/"ollama").mkdir(parents=True)
    (tmp_path/"ollama"/"ollama.exe").write_bytes(b"fake")
    manifest=(tmp_path/"ollama"/"models"/"manifests"/"registry.ollama.ai"/"library"/"qwen3.5"/"0.8b")
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}")
    blobs=tmp_path/"ollama"/"models"/"blobs"
    blobs.mkdir()
    (blobs/"sha256-test").write_bytes(b"test")
    voice=tmp_path/"piper"/"voices"/"fa_IR-amir-medium.onnx"
    voice.parent.mkdir(parents=True)
    voice.write_bytes(b"test")
    voice.with_suffix(".onnx.json").write_text("{}")
    (tmp_path/"piper"/"piper.exe").write_bytes(b"fake")
    assert engines.vision_status()["model_ready"]
    assert engines.voice_status()["ready"]
    assert engines.vision_status()["model"] == "qwen3.5:0.8b"


def test_local_vision_server_address_only():
    assert engines.VISION_URL == "http://127.0.0.1:11437"
    assert engines.MEMORY_MIN_GB >= 4
