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
from embedded_engines import VISION_MODEL, VISION_URL as OLLAMA_URL, vision_status, voice_status, create_persian_wav, whisper_model_dir



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
    return vision_status()


def moss_tts_status() -> dict:
    return voice_status()


def ensure_moss_tts_service(progress=None) -> None:
    if progress:
        progress(3, "بررسی موتور فارسی داخلی")
    if not voice_status()["ready"]:
        raise RuntimeError(voice_status()["message"])


def _ollama_chat(messages: list[dict], *, json_mode: bool = False, timeout: int = 600, keep_alive: str = "45s") -> str:
    payload: dict[str, Any] = {
        "model": VISION_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {"temperature": 0.2, "num_ctx": recommended_profile()["vision_context"], "num_predict": 1400, "num_thread": recommended_profile()["vision_threads"]},
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
    batch_size = 1
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
    observations = [x[:550] for x in observations]
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
    if not voice_status()["ready"]:
        raise RuntimeError(voice_status()["message"])
    lines = script.get("dialogues", [])
    if not lines:
        raise RuntimeError("هیچ دیالوگی برای تولید صدا وجود ندارد.")
    outdir = project_dir / "renders" / "animation_dub"
    outdir.mkdir(parents=True, exist_ok=True)
    for i, line in enumerate(lines):
        if progress:
            progress(5 + int(90 * i / len(lines)), f"صداسازی دیالوگ {i+1} از {len(lines)}")
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        cid = str(line.get("character_id") or "")
        # Bundled Piper Amir has ONE distinct voice. Alternate speed per character.
        speed = (0.92, 1.0, 1.08)[sum(ord(ch) for ch in cid) % 3]
        filename = f"line_{i+1:03d}_{uuid.uuid4().hex[:6]}.wav"
        create_persian_wav(text, outdir / filename, speed=speed)
        line["audio_file"] = "animation_dub/" + filename
    if progress:
        progress(100, "صدای فارسی داخلی آماده شد")
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
