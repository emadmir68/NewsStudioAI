"""CPU resource presets: deterministic tests with no AI model downloads."""
from hardware_profile import profile_for, recommended_profile


def test_core_i5_12500_16gb_preset():
    settings = profile_for(16.0, 12)
    assert settings["name"] == "balanced_16gb"
    assert settings["whisper_model"] == "base"
    assert settings["whisper_threads"] == 2
    assert settings["vision_threads"] == 2
    assert settings["frames"] == 12
    assert settings["frame_width"] == 512
    assert settings["tts_threads"] == 2
    assert settings["render_threads"] == 2
    assert settings["compute_type"] == "int8"
    assert settings["uses_discrete_gpu"] is False


def test_limited_ram_defaults_are_lightweight():
    settings = profile_for(8.0, 4)
    assert settings["name"] == "light_cpu"
    assert settings["whisper_model"] == "tiny"
    assert settings["frames"] == 8
    assert settings["frame_width"] == 384
    assert settings["render_threads"] == 2
    assert settings["vision_context"] == 1536


def test_single_core_is_bounded():
    settings = profile_for(16.0, 1)
    assert 1 <= settings["render_threads"] <= 4
    assert 1 <= settings["tts_threads"] <= 4


def test_real_system_profile_is_serializable():
    settings = recommended_profile()
    assert settings["device"] == "cpu"
    assert settings["compute_type"] == "int8"
    assert settings["installed_ram_gb"] >= 0


def test_safety_restrictions_for_16gb_system():
    profile = profile_for(16.0, 12)
    assert profile["vision_context"] == 2048
    assert profile["render_crf"] >= 23
    assert profile["frames"] <= 12
    assert profile["whisper_threads"] <= 2
    assert profile["vision_threads"] <= 2
