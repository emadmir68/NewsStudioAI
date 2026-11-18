"""Local-first animation analysis and Persian dubbing helpers for News Studio AI.

Optional engines:
- Ollama + qwen3-vl:2b for visual understanding and script generation.
- MOSS-TTS-Nano local HTTP service for Persian speech synthesis.
All media processing remains on the user's machine.
"""
from __future__ import annotations

import base64
import gc
import json
import math
import mimetypes
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from hardware_profile import recommended_profile

OLLAMA_URL = "http://127.0.0.1:11434"
VISION_MODEL = "qwen3-vl:2b"
MOSS_TTS_URL = "http://127.0.0.1:18083"


def _json_request(url: str, method: str = "GET", payload: dict | None = None, timeout: int = 20) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def ollama_status() -> dict:
    try:
        data = _json_request(f"{OLLAMA_URL}/api/tags", timeout=4)
        names = [str(x.get("name", "")) for x in data.get("models", [])]
        found = any(n == VISION_MODEL or n.startswith(VISION_MODEL + "-") for n in names)
        return {
            "available": True,
            "model_ready": found,
            "model": VISION_MODEL,
            "models": names,
            "message": "مدل بینایی آماده است." if found else f"برای فعال‌سازی، مدل {VISION_MODEL} را دریافت کنید.",
        }
    except Exception:
        return {
            "available": False,
            "model_ready": False,
            "model": VISION_MODEL,
            "models": [],
            "message": "Ollama نصب یا اجرا نشده است.",
        }


def moss_tts_status() -> dict:
    try:
        health = _json_request(f"{MOSS_TTS_URL}/health", timeout=4)
        warm = _json_request(f"{MOSS_TTS_URL}/api/warmup-status", timeout=4)
        ready = bool(health.get("status") == "ok" and warm.get("ready"))
        return {
            "available": True,
            "ready": ready,
            "failed": bool(warm.get("failed")),
            "message": "موتور صدای فارسی آماده است." if ready else str(warm.get("status_text") or warm.get("message") or "موتور صدا در حال آماده‌سازی است."),
        }
    except Exception:
        return {
            "available": False,
            "ready": False,
            "message": "موتور صدای محلی نصب یا اجرا نشده است.",
        }


def ensure_moss_tts_service(progress: Callable[[int, str], None] | None = None, timeout: int = 1800) -> None:
    status = moss_tts_status()
    if status.get("ready"):
        return
    process = None
    if not status.get("available"):
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NewsStudioAI" / "animation-ai"
        python = root / "venv" / "Scripts" / "python.exe"
        repo = root / "MOSS-TTS-Nano"
        if not python.is_file() or not (repo / "app.py").is_file():
            raise RuntimeError("موتور صدای فارسی نصب نشده است. ابتدا اسکریپت نصب موتورهای هوشمند را اجرا کنید.")
        log_dir = root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "moss-tts.log"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                [str(python), "app.py", "--device", "cpu", "--host", "127.0.0.1", "--port", "18083"],
                cwd=str(repo), stdout=log, stderr=log, creationflags=flags,
            )
    started = time.time()
    while time.time() - started < timeout:
        status = moss_tts_status()
        if status.get("ready"):
            return
        if status.get("failed"):
            raise RuntimeError(status.get("message") or "موتور صدای فارسی هنگام آماده‌سازی خطا داد.")
        if process is not None and process.poll() is not None:
            raise RuntimeError("موتور صدای فارسی متوقف شد. گزارش خطا در پوشه LocalAppData\\\\NewsStudioAI\\\\animation-ai\\\\logs قرار دارد.")
        elapsed = int(time.time() - started)
        if progress:
            progress(min(28, 4 + int(24 * elapsed / max(1, timeout))), status.get("message") or "در حال بارگذاری مدل صدای فارسی")
        time.sleep(3)
    raise RuntimeError("آماده‌سازی موتور صدای فارسی بیش از حد طول کشید. اتصال اینترنت و گزارش خطا را بررسی کنید.")


def _ollama_chat(messages: list[dict], *, json_mode: bool = False, timeout: int = 600, keep_alive: str = "10m") -> str:
    payload: dict[str, Any] = {
        "model": VISION_MODEL,
        "messages": messages,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"temperature": 0.2, "num_ctx": recommended_profile()["vision_context"], "num_predict": 4096, "num_thread": recommended_profile()["vision_threads"]},
    }
    if json_mode:
        payload["format"] = "json"
    result = _json_request(f"{OLLAMA_URL}/api/chat", "POST", payload, timeout=timeout)
    return str((result.get("message") or {}).get("content") or "").strip()


def _extract_json(text: str) -> dict:
    raw = str(text or "").strip()
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        value = json.loads(raw[start:end + 1])
        if isinstance(value, dict):
            return value
    raise ValueError("مدل پاسخ ساختاریافته و قابل‌خواندن تولید نکرد؛ دوباره تحلیل را اجرا کنید.")


def extract_animation_frames(video: Path, frame_dir: Path, duration: float, ffmpeg: str, max_frames: int | None = None) -> list[dict]:
    if not ffmpeg:
        raise RuntimeError("FFmpeg در دسترس نیست.")
    settings = recommended_profile()
    max_frames = max_frames or settings["frames"]
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("frame_*.jpg"):
        old.unlink(missing_ok=True)
    safe_duration = max(1.0, float(duration or 1.0))
    interval = max(2.5, safe_duration / max_frames)
    output_pattern = frame_dir / "frame_%03d.jpg"
    vf = f"fps=1/{interval:.4f},scale={settings['frame_width']}:-2"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", vf, "-frames:v", str(max_frames), "-q:v", "4", str(output_pattern),
    ]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if run.returncode:
        raise RuntimeError("استخراج فریم‌های انیمیشن ناموفق بود: " + (run.stderr or "")[-1200:])
    files = sorted(frame_dir.glob("frame_*.jpg"))
    if not files:
        raise RuntimeError("هیچ فریمی از ویدئو استخراج نشد.")
    frames = []
    for index, path in enumerate(files):
        frames.append({"path": path, "time": min(safe_duration, index * interval)})
    return frames


def transcribe_animation_audio(video: Path, progress: Callable[[int, str], None] | None = None) -> dict:
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return {"language": "", "segments": [], "note": "موتور Whisper در این نصب در دسترس نیست."}
    model = None
    try:
        if progress:
            progress(5, "تشخیص گفتار اصلی و زبان ویدئو")
        settings = recommended_profile()
        model = WhisperModel(settings["whisper_model"], device="cpu", compute_type="int8", cpu_threads=settings["whisper_threads"])
        segments, info = model.transcribe(
            str(video), task="transcribe", language=None, beam_size=1,
            vad_filter=True, condition_on_previous_text=False,
        )
        found = []
        for segment in segments:
            text = str(getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            no_speech = float(getattr(segment, "no_speech_prob", 0.0) or 0.0)
            avg_logprob = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
            if no_speech > 0.65 or avg_logprob < -1.5:
                continue
            found.append({
                "start": round(max(0.0, float(segment.start)), 2),
                "end": round(max(float(segment.start) + 0.1, float(segment.end)), 2),
                "text": text[:500],
            })
            if len(found) >= 200:
                break
        language = str(getattr(info, "language", "") or "")
        note = "" if found else "گفتار قابل‌اعتماد و قابل‌تشخیصی در صدای اصلی پیدا نشد."
        return {"language": language, "segments": found, "note": note}
    except Exception as exc:
        return {"language": "", "segments": [], "note": "رونویسی صدای اصلی انجام نشد: " + str(exc)[:300]}
    finally:
        model = None
        gc.collect()


def _frame_observations(frames: list[dict], progress: Callable[[int, str], None] | None = None) -> list[str]:
    observations: list[str] = []
    batch_size = 4
    batches = [frames[i:i + batch_size] for i in range(0, len(frames), batch_size)]
    for batch_index, batch in enumerate(batches):
        image_data = []
        labels = []
        for frame in batch:
            image_data.append(base64.b64encode(Path(frame["path"]).read_bytes()).decode("ascii"))
            labels.append(f"{frame['time']:.1f} ثانیه")
        prompt = (
            "این تصاویر فریم‌هایی از یک انیمیشن واحد هستند و به ترتیب زمانی ارائه شده‌اند. "
            "برچسب زمان هر تصویر در متن آمده است. فقط آنچه واقعاً در تصویر دیده می‌شود گزارش کن. "
            "شخصیت‌های تکرارشونده را با توصیف ظاهری ثابت دنبال کن؛ اگر هویت یکسان قطعی نیست، حدس نزن. "
            "برای هر فریم زمان، محیط، شخصیت‌های قابل مشاهده، حرکت، حالت چهره و رویداد را ثبت کن. "
            "دیالوگ نساز و از تصویر چیزی را که دیده نمی‌شود نتیجه نگیر. "
            "پاسخ فارسی و فشرده باشد. قالب JSON: "
            '{"observations":[{"time":0,"setting":"","characters":[{"visual_id":"A","appearance":"","expression":"","action":""}],"event":"","mood":""}]} '
            "زمان تصاویر به ترتیب: " + "، ".join(labels)
        )
        content = _ollama_chat(
            [{"role": "user", "content": prompt, "images": image_data}],
            json_mode=True,
            timeout=600,
        )
        try:
            parsed = _extract_json(content)
            observations.append(json.dumps(parsed, ensure_ascii=False))
        except Exception:
            observations.append(content[:5000])
        if progress:
            progress(12 + int(48 * (batch_index + 1) / max(1, len(batches))), f"تحلیل تصویری بخش {batch_index + 1} از {len(batches)}")
    return observations


def _sanitize_script(data: dict, duration: float) -> dict:
    duration = max(1.0, float(duration or 1.0))
    characters = []
    seen = set()
    for index, item in enumerate(data.get("characters", [])[:12]):
        if not isinstance(item, dict):
            continue
        cid = re.sub(r"[^a-zA-Z0-9_-]", "", str(item.get("id") or f"c{index + 1}"))[:24] or f"c{index + 1}"
        if cid in seen:
            cid = f"{cid}_{index + 1}"
        seen.add(cid)
        characters.append({
            "id": cid,
            "name": str(item.get("name") or f"شخصیت {index + 1}")[:60],
            "appearance": str(item.get("appearance") or item.get("visual_description") or "")[:400],
            "voice_profile": str(item.get("voice_profile") or "صدای طبیعی و محاوره‌ای")[:240],
            "voice_reference": "",
        })
    if not characters:
        characters = [{
            "id": "narrator", "name": "راوی", "appearance": "راوی خارج از تصویر",
            "voice_profile": "صدای راوی فارسی ایرانی، گرم و واضح", "voice_reference": "",
        }]
    valid_ids = {x["id"] for x in characters}
    dialogues = []
    for index, item in enumerate(data.get("dialogues", [])[:160]):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:700]
        if not text:
            continue
        try:
            start = max(0.0, min(max(0.0, duration - 0.25), float(item.get("start", 0))))
        except Exception:
            start = 0.0
        try:
            end = max(start + 0.25, min(duration, float(item.get("end", start + max(1.5, len(text) * 0.055)))))
        except Exception:
            end = min(duration, start + max(1.5, len(text) * 0.055))
        if end <= start:
            start = max(0.0, duration - 0.5)
            end = duration
        cid = str(item.get("character_id") or "narrator")
        if cid not in valid_ids:
            cid = characters[0]["id"]
        dialogues.append({
            "id": re.sub(r"[^a-zA-Z0-9_-]", "", str(item.get("id") or f"d{index + 1}"))[:24] or f"d{index + 1}",
            "start": round(start, 2),
            "end": round(end, 2),
            "character_id": cid,
            "text": text,
            "emotion": str(item.get("emotion") or "طبیعی")[:60],
            "delivery": str(item.get("delivery") or "محاوره‌ای و روان")[:100],
            "audio_file": "",
        })
    scenes = []
    for index, item in enumerate(data.get("scenes", [])[:80]):
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, min(duration, float(item.get("start", 0))))
            end = max(start, min(duration, float(item.get("end", duration))))
        except Exception:
            continue
        scenes.append({
            "id": str(item.get("id") or f"s{index + 1}")[:24],
            "start": round(start, 2), "end": round(end, 2),
            "description": str(item.get("description") or item.get("event") or "")[:500],
            "mood": str(item.get("mood") or "")[:100],
        })
    return {
        "title": str(data.get("title") or "دوبله انیمیشن")[:120],
        "summary": str(data.get("summary") or "")[:2000],
        "characters": characters,
        "scenes": sorted(scenes, key=lambda x: x["start"]),
        "dialogues": sorted(dialogues, key=lambda x: (x["start"], x["end"])),
    }


def analyze_animation(video: Path, frame_dir: Path, duration: float, ffmpeg: str,
                      progress: Callable[[int, str], None] | None = None) -> dict:
    transcript = transcribe_animation_audio(video, progress)
    frames = extract_animation_frames(video, frame_dir, duration, ffmpeg)
    if progress:
        progress(10, f"{len(frames)} فریم برای تحلیل آماده شد")
    observations = _frame_observations(frames, progress)
    prompt = (
        "بر اساس گزارش‌های مشاهده‌ای زیر که از فریم‌های زمان‌دار یک انیمیشن استخراج شده‌اند، "
        "یک طرح دوبله کامل و منسجم به فارسی محاوره‌ای طبیعی ایران بنویس. اگر گفتار اصلی تشخیص داده شده، معنای آن را دقیق و وفادار حفظ کن و آن را به فارسی طبیعی بازنویسی کن؛ زمان‌های گفتار اصلی مرجع زمان‌بندی باشند. "
        "داستان را از ابتدا تا انتها دنبال کن. شخصیت‌های تکراری را یک شخصیت ثابت نگه دار. "
        "دیالوگ‌ها کوتاه، قابل اجرا، احساسی و متناسب با اتفاقات باشند. "
        "برای هر شخصیت صدای پیشنهادی متفاوت تعریف کن. "
        "اگر مشخص نیست چه کسی صحبت می‌کند، دیالوگ را به راوی نسبت بده؛ دیالوگ را به شخصیت اشتباه نسبت نده. "
        "هیچ اتفاق، رابطه، نام یا اطلاعاتی را که از گزارش‌ها پشتیبانی نمی‌شود قطعی جلوه نده. "
        "زمان شروع و پایان دیالوگ‌ها تقریبی و در محدوده طول ویدئو باشد؛ هم‌پوشانی غیرضروری ایجاد نکن. "
        "برای ویدئوی بی‌کلام، دیالوگ خلاقانه ولی وفادار به تصویر بنویس. "
        "پاسخ فقط JSON معتبر باشد با این ساختار: "
        '{"title":"","summary":"","characters":[{"id":"c1","name":"","appearance":"","voice_profile":""}],'
        '"scenes":[{"id":"s1","start":0,"end":5,"description":"","mood":""}],'
        '"dialogues":[{"id":"d1","start":0.5,"end":3.5,"character_id":"c1","text":"","emotion":"","delivery":""}]} '
        f"مدت کل ویدئو: {duration:.2f} ثانیه. "
        "گفتار تشخیص‌داده‌شده از صدای اصلی (در صورت وجود، متن و زمان‌ها را مبنا قرار بده):\n" + "\n".join([f"{x['start']:.2f}-{x['end']:.2f}: {x['text']}" for x in transcript.get("segments", [])]) + "\n\nگزارش فریم‌ها به ترتیب زمانی:\n" + "\n".join(observations)
    )
    if progress:
        progress(68, "نوشتن فیلمنامه و دیالوگ‌های فارسی")
    content = _ollama_chat([{"role": "user", "content": prompt}], json_mode=True, timeout=900, keep_alive="0")
    script = _sanitize_script(_extract_json(content), duration)
    script["frame_count"] = len(frames)
    script["source_transcript"] = transcript.get("segments", [])
    script["source_language"] = transcript.get("language", "")
    script["transcription_note"] = transcript.get("note", "")
    script["analysis_model"] = VISION_MODEL
    script["created_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    if progress:
        progress(100, "تحلیل و فیلمنامه فارسی آماده شد")
    return script


def _multipart_request(url: str, fields: dict[str, str], file_field: str, file_path: Path, timeout: int = 900) -> dict:
    boundary = "----NewsStudioAI" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{file_path.name}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8") + file_path.read_bytes() + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    body = b"".join(chunks)
    req = Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def generate_voice_tracks(project_dir: Path, script: dict, progress: Callable[[int, str], None] | None = None) -> dict:
    status = moss_tts_status()
    if not status["available"]:
        raise RuntimeError("موتور صدای فارسی در دسترس نیست. راهنمای نصب موتور دوبله هوشمند را اجرا کنید.")
    if not status["ready"]:
        raise RuntimeError("موتور صدای فارسی هنوز آماده نشده است؛ چند لحظه صبر کنید و دوباره تلاش کنید.")
    characters = {str(c["id"]): c for c in script.get("characters", [])}
    dialogues = script.get("dialogues", [])
    if not dialogues:
        raise RuntimeError("هیچ دیالوگی برای تولید صدا وجود ندارد.")
    output_dir = project_dir / "renders" / "animation_dub"
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = 0
    for index, line in enumerate(dialogues):
        cid = str(line.get("character_id") or "")
        character = characters.get(cid) or {}
        reference = str(character.get("voice_reference") or "")
        if not reference:
            raise RuntimeError(f"برای شخصیت «{character.get('name') or cid}» نمونه صدای مرجع بارگذاری نشده است.")
        reference_path = (project_dir / "assets" / Path(reference).name).resolve()
        if not reference_path.is_file() or reference_path.parent != (project_dir / "assets").resolve():
            raise RuntimeError(f"فایل نمونه صدای شخصیت «{character.get('name') or cid}» پیدا نشد.")
        text = str(line.get("text") or "").strip()
        max_frames = max(90, min(375, int(len(text) * 2.2 + 70)))
        response = _multipart_request(
            f"{MOSS_TTS_URL}/api/generate",
            {
                "text": text,
                "max_new_frames": str(max_frames),
                "voice_clone_max_text_tokens": "75",
                "enable_text_normalization": "0",
                "enable_normalize_tts_text": "1",
                "cpu_threads": str(recommended_profile()["tts_threads"]),
                "do_sample": "1",
                "text_temperature": "1.0",
                "text_top_p": "1.0",
                "text_top_k": "50",
                "audio_temperature": "0.8",
                "audio_top_p": "0.95",
                "audio_top_k": "25",
                "audio_repetition_penalty": "1.2",
            },
            "prompt_audio", reference_path,
        )
        encoded = response.get("audio_base64")
        if not encoded:
            raise RuntimeError(str(response.get("error") or "موتور صدا خروجی صوتی تولید نکرد."))
        filename = f"line_{index + 1:03d}_{uuid.uuid4().hex[:6]}.wav"
        (output_dir / filename).write_bytes(base64.b64decode(encoded))
        line["audio_file"] = f"animation_dub/{filename}"
        completed += 1
        if progress:
            progress(5 + int(95 * completed / len(dialogues)), f"ساخت صدای دیالوگ {completed} از {len(dialogues)}")
    return script


def _probe_audio_duration(path: Path, ffprobe: str) -> float:
    if not ffprobe:
        return 0.0
    try:
        run = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return max(0.0, float((run.stdout or "0").strip())) if run.returncode == 0 else 0.0
    except Exception:
        return 0.0


def render_dubbed_video(project_dir: Path, source: Path, script: dict, output_path: Path,
                        ffmpeg: str, ffprobe: str, duration: float,
                        keep_original_audio: bool = False) -> dict:
    if not ffmpeg:
        raise RuntimeError("FFmpeg در دسترس نیست.")
    dialogues = [x for x in script.get("dialogues", []) if x.get("audio_file")]
    if not dialogues:
        raise RuntimeError("ابتدا صدای دیالوگ‌ها را تولید کنید.")
    inputs = ["-i", str(source)]
    filters = []
    voice_labels = []
    warnings = []
    for index, line in enumerate(dialogues):
        relative = Path(str(line["audio_file"]).replace("\\", "/")).name
        audio_path = project_dir / "renders" / "animation_dub" / relative
        if not audio_path.is_file():
            raise RuntimeError(f"فایل صدای دیالوگ {index + 1} پیدا نشد.")
        input_index = index + 1
        inputs += ["-i", str(audio_path)]
        start = max(0.0, float(line.get("start", 0)))
        end = max(start + 0.25, float(line.get("end", start + 3)))
        target = max(0.25, end - start)
        actual = _probe_audio_duration(audio_path, ffprobe)
        chain = f"[{input_index}:a]aresample=48000"
        if actual > target * 1.08 and actual > 0:
            factor = min(1.35, actual / target)
            chain += f",atempo={factor:.4f}"
            if actual / factor > target * 1.12:
                warnings.append(f"دیالوگ {index + 1} از زمان تعیین‌شده طولانی‌تر است.")
        delay = int(round(start * 1000))
        chain += f",adelay={delay}|{delay}[v{index}]"
        filters.append(chain)
        voice_labels.append(f"[v{index}]")
    filters.append("".join(voice_labels) + f"amix=inputs={len(voice_labels)}:duration=longest:dropout_transition=0:normalize=0[dub]")
    audio_label = "dub"
    source_has_audio = False
    try:
        probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(source)], capture_output=True, text=True, timeout=30)
        source_has_audio = bool((probe.stdout or "").strip())
    except Exception:
        pass
    if keep_original_audio and source_has_audio:
        filters.append("[0:a]aresample=48000,volume=0.10[original]")
        filters.append("[original][dub]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[final]")
        audio_label = "final"
    filters.append(f"[{audio_label}]apad=whole_dur={max(1.0, duration):.3f},atrim=duration={max(1.0, duration):.3f}[outa]")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_cmd = [
        ffmpeg, "-hide_banner", "-y", *inputs,
        "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
        "-map", "0:v:0", "-map", "[outa]", "-t", f"{max(1.0, duration):.3f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(output_path),
    ]
    run = subprocess.run(base_cmd, capture_output=True, text=True, timeout=7200)
    if run.returncode:
        # Fallback for containers/codecs that cannot be muxed directly into MP4.
        retry = base_cmd.copy()
        video_codec = retry.index("-c:v") + 1
        settings = recommended_profile()
        retry[video_codec:video_codec + 1] = ["libx264", "-preset", settings["render_preset"], "-crf", str(settings["render_crf"]), "-threads", str(settings["render_threads"]), "-pix_fmt", "yuv420p"]
        run = subprocess.run(retry, capture_output=True, text=True, timeout=7200)
    if run.returncode:
        raise RuntimeError("رندر دوبله ناموفق بود: " + (run.stderr or "")[-1800:])
    return {"filename": output_path.name, "warnings": warnings}
