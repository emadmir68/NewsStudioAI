"""Bundled, CPU-limited vision and Persian TTS engines.

Never install dependencies or download model weights at runtime.
All paths remain inside the News Studio AI installation.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from hardware_profile import available_ram_gb

VISION_MODEL = "qwen3.5:0.8b"
VISION_HOST = "127.0.0.1"
VISION_PORT = 11437
VISION_URL = f"http://{VISION_HOST}:{VISION_PORT}"
MEMORY_MIN_GB = 4.5
_PROCESS = None
_LOCK = threading.RLock()
WIN_FLAGS = (getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))


def installed_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def engine_root() -> Path:
    root = installed_root()
    installed = root / "ai"
    return installed if installed.is_dir() else root / "vendor" / "ai"


def vision_binary() -> Path:
    return engine_root() / "ollama" / ("ollama.exe" if os.name == "nt" else "ollama")


def vision_models() -> Path:
    return engine_root() / "ollama" / "models"


def model_manifest() -> Path:
    return vision_models() / "manifests" / "registry.ollama.ai" / "library" / "qwen3.5" / "0.8b"


def whisper_model_dir() -> Path:
    return engine_root() / "whisper" / "base"


def piper_binary() -> Path:
    return engine_root() / "piper" / ("piper.exe" if os.name == "nt" else "piper")


def piper_voice() -> Path:
    return engine_root() / "piper" / "voices" / "fa_IR-amir-medium.onnx"


def voice_status() -> dict:
    model = piper_voice()
    binary = piper_binary()
    ready = binary.is_file() and model.is_file() and model.with_suffix(".onnx.json").is_file()
    return {
        "available": ready,
        "ready": ready,
        "internal": True,
        "voice": "fa_IR-amir-medium",
        "message": "موتور فارسی Piper همراه نرم‌افزار آماده است." if ready
                   else "فایل‌های صدای فارسی داخل بسته نصب یافت نشدند؛ از نصب‌کننده کامل استفاده کنید.",
    }


def vision_status() -> dict:
    binary = vision_binary()
    manifest = model_manifest()
    ready = binary.is_file() and manifest.is_file() and bool(list((vision_models() / "blobs").glob("*")))
    return {
        "available": ready,
        "model_ready": ready,
        "internal": True,
        "model": VISION_MODEL,
        "message": "مدل تحلیل تصویر همراه نرم‌افزار نصب شده است." if ready
                   else "فایل‌های مدل بینایی داخل بسته نصب یافت نشدند؛ از نصب‌کننده کامل استفاده کنید.",
    }


def _vision_server_up() -> bool:
    try:
        with urlopen(Request(f"{VISION_URL}/api/version"), timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_vision_started(progress=None, timeout: int = 50) -> None:
    global _PROCESS
    if not vision_status()["model_ready"]:
        raise RuntimeError("مدل بینایی داخلی نصب نشده است. نسخه کامل آفلاین News Studio AI را نصب کنید.")
    free = available_ram_gb()
    if free and free < MEMORY_MIN_GB:
        raise RuntimeError(f"برای محافظت از سیستم، تحلیل شروع نشد: فقط {free} گیگابایت حافظه آزاد است.")
    with _LOCK:
        if _vision_server_up():
            return
        if _PROCESS is not None and _PROCESS.poll() is None:
            pass
        else:
            env = dict(os.environ)
            env.update({
                "OLLAMA_MODELS": str(vision_models()),
                "OLLAMA_HOST": f"{VISION_HOST}:{VISION_PORT}",
                "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_MAX_LOADED_MODELS": "1",
                "OLLAMA_MAX_QUEUE": "1",
                "OLLAMA_CONTEXT_LENGTH": "2048",
                "OLLAMA_KEEP_ALIVE": "0s",
                "CUDA_VISIBLE_DEVICES": "-1",
                "HIP_VISIBLE_DEVICES": "-1",
                "ROCR_VISIBLE_DEVICES": "-1",
                "OLLAMA_LLM_LIBRARY": "cpu",
            })
            startupinfo = None
            _PROCESS = subprocess.Popen(
                [str(vision_binary()), "serve"], cwd=str(vision_binary().parent),
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=WIN_FLAGS if os.name == "nt" else 0,
                startupinfo=startupinfo,
            )
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if progress:
            progress(3, "راه‌اندازی موتور تحلیل تصویر داخلی")
        if _vision_server_up():
            return
        if _PROCESS is not None and _PROCESS.poll() is not None:
            raise RuntimeError("موتور داخلی تصویر هنگام شروع بسته شد. برای بررسی مشکل گزارش‌های ویندوز را بررسی کنید.")
        time.sleep(1)
    shutdown_vision()
    raise RuntimeError("موتور تصویر در زمان مجاز راه‌اندازی نشد؛ اجرای پردازش برای جلوگیری از هنگ متوقف شد.")


def shutdown_vision():
    global _PROCESS
    with _LOCK:
        proc, _PROCESS = _PROCESS, None
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def create_persian_wav(text: str, dest: Path, *, speed: float = 1.0, timeout: int = 180) -> None:
    status = voice_status()
    if not status["ready"]:
        raise RuntimeError(status["message"])
    free = available_ram_gb()
    if free and free < 2.0:
        raise RuntimeError(f"رم آزاد کافی نیست ({free} گیگابایت).")
    clean = str(text or "").strip()
    if not clean or len(clean) > 700:
        raise ValueError("هر دیالوگ باید ۱ تا ۷۰۰ نویسه باشد.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
    # Piper length_scale: higher is slower, lower is faster.
    length_scale = min(1.18, max(0.85, float(speed)))
    cmd = [
        str(piper_binary()), "--model", str(piper_voice()),
        "--output_file", str(dest), "--length_scale", f"{length_scale:.2f}",
    ]
    result = subprocess.run(cmd, input=(clean + "\n").encode("utf-8"),
                            cwd=str(piper_binary().parent), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout,
                            creationflags=WIN_FLAGS if os.name == "nt" else 0)
    if result.returncode or not dest.exists() or dest.stat().st_size < 1000:
        raise RuntimeError("موتور داخلی صدای فارسی فایل سالم تولید نکرد: "
                           + result.stderr.decode("utf-8", "replace")[-350:])


atexit.register(shutdown_vision)
