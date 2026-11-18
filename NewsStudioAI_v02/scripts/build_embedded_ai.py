"""Prepare self-contained CPU AI engines for News Studio AI's offline Windows Setup.

Build-time network access only. The installed application never downloads
model weights, installs Python packages, or executes shell setup scripts.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / "vendor" / "ai"
DOWNLOADS = ROOT / "build-downloads"

OLLAMA_ZIP = "https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-windows-amd64.zip"
PIPER_ZIP = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fa/fa_IR/amir/medium/"
WHISPER_BASE = "https://huggingface.co/Systran/faster-whisper-base/resolve/main/"
VISION_MODEL = "qwen3.5:0.8b"
HOST = "127.0.0.1:11437"


def download(url: str, dest: Path, minimum: int = 128) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size >= minimum:
        print(f"Using cached {dest.name} ({dest.stat().st_size:,} bytes)",flush=True)
        return dest
    for attempt in range(1,4):
        try:
            tmp = dest.with_suffix(dest.suffix + ".part")
            request = urllib.request.Request(url, headers={"User-Agent": "NewsStudioAI-CI/0.4.0"})
            with urllib.request.urlopen(request, timeout=150) as response, tmp.open("wb") as out:
                shutil.copyfileobj(response, out, length=4 * 1024 * 1024)
            if tmp.stat().st_size < minimum:
                raise RuntimeError(f"{dest.name} too small: {tmp.stat().st_size}")
            tmp.replace(dest)
            print(f"Downloaded {dest.name}: {dest.stat().st_size:,} bytes", flush=True)
            return dest
        except Exception as error:
            print(f"Retry {attempt}: {url}: {error}", flush=True)
            if attempt == 3: raise
            time.sleep(6 * attempt)
    raise RuntimeError("unreachable")


def extract_ollama(zip_path: Path) -> Path:
    dest = AI / "ollama"
    dest.mkdir(parents=True, exist_ok=True)
    selected = []
    excluded = ("cuda", "rocm", "cublas", "cudart", "cudnn", "nvrtc",
                "vulkan", "hipblas", "rocblas", "hiprtc", "oneapi", "sycl", "mlx")
    with zipfile.ZipFile(zip_path) as archive:
        entries=archive.infolist()
        print("OLLAMA ZIP ENTRY SAMPLE:",[x.filename for x in entries[:25]],flush=True)
        for item in entries:
            if item.is_dir(): continue
            name = item.filename.replace("\\","/")
            lower = name.lower()
            parts = lower.split("/")
            if len(parts) > 1 and parts[0] not in ("lib", "ollama", "ollama-windows-amd64"):
                continue
            if lower.endswith("/ollama.exe") or lower=="ollama.exe":
                target=dest/"ollama.exe"
            elif "/lib/ollama/" in lower or lower.startswith("lib/ollama/"):
                if any(x in lower for x in excluded):
                    continue
                rel = lower[lower.find("lib/ollama/"):]
                target=dest/rel
            else:
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(item) as src,target.open("wb") as dst:
                shutil.copyfileobj(src,dst,length=1024*1024)
            selected.append((str(target.relative_to(dest)),target.stat().st_size))
    print("OLLAMA SELECTED:",selected,flush=True)
    binary=dest/"ollama.exe"
    if not binary.exists():
        raise RuntimeError("ollama.exe was not found in the standalone archive")
    return binary


def extract_piper(zip_path:Path)->Path:
    dest=AI/"piper"
    dest.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        names=[x.filename.replace("\\","/") for x in archive.infolist()]
        print("PIPER ZIP ENTRY SAMPLE:",names[:25],flush=True)
        for item in archive.infolist():
            if item.is_dir(): continue
            raw=item.filename.replace("\\","/")
            parts=raw.split("/")
            if raw.startswith("piper/"):
                raw="/".join(parts[1:])
            if not raw or ".." in Path(raw).parts:
                continue
            target=dest/raw
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(item) as src,target.open("wb") as dst:
                shutil.copyfileobj(src,dst,length=1024*1024)
    binary=dest/"piper.exe"
    if not binary.exists():
        raise RuntimeError("piper.exe was not found in Windows Piper archive")
    return binary


def pull_vision(binary:Path)->None:
    dest=AI/"ollama"/"models"
    dest.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ)
    env.update({
        "OLLAMA_HOST":HOST,
        "OLLAMA_MODELS":str(dest.resolve()),
        "OLLAMA_NUM_PARALLEL":"1",
        "OLLAMA_MAX_LOADED_MODELS":"1",
        "OLLAMA_KEEP_ALIVE":"0s",
        "CUDA_VISIBLE_DEVICES":"-1",
        "ROCR_VISIBLE_DEVICES":"-1",
        "OLLAMA_LLM_LIBRARY":"cpu",
    })
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    log=(DOWNLOADS/"ollama-server.log").open("wb")
    server=subprocess.Popen([str(binary),"serve"],cwd=str(binary.parent),env=env,
                             stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    try:
        for attempt in range(90):
            if server.poll() is not None:
                raise RuntimeError("Ollama server terminated: "+(DOWNLOADS/"ollama-server.log").read_text(errors="replace")[-4000:])
            try:
                with urllib.request.urlopen(f"http://{HOST}/api/version",timeout=2) as response:
                    if response.status==200:break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Portable Ollama did not start")
        print("Downloading bundled visual model",VISION_MODEL,flush=True)
        subprocess.run([str(binary),"pull",VISION_MODEL],cwd=str(binary.parent),env=env,check=True,timeout=1800)
        result=subprocess.run([str(binary),"list"],cwd=str(binary.parent),env=env,
                              capture_output=True,text=True,check=True,timeout=50)
        print("MODEL LIST:",result.stdout,flush=True)
        manifest=dest/"manifests"/"registry.ollama.ai"/"library"/"qwen3.5"/"0.8b"
        if not manifest.is_file() or not list((dest/"blobs").glob("*")):
            raise RuntimeError("Downloaded Qwen3.5 manifest or blobs missing")
        print("MODEL SIZE:",sum(x.stat().st_size for x in (dest/"blobs").glob("*") if x.is_file()),flush=True)
    finally:
        try:
            subprocess.run(["taskkill","/PID",str(server.pid),"/T","/F"],check=False,timeout=15,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           creationflags=flags)
        except Exception:
            server.kill()
        log.close()


def prepare_voices():
    directory=AI/"piper"/"voices"
    for filename in ("fa_IR-amir-medium.onnx","fa_IR-amir-medium.onnx.json"):
        download(VOICE_BASE+filename,directory/filename,minimum=100 if filename.endswith(".json") else 20_000_000)


def prepare_whisper():
    directory=AI/"whisper"/"base"
    for filename in ("model.bin","config.json","tokenizer.json","vocabulary.txt"):
        download(WHISPER_BASE+filename,directory/filename,minimum=200 if filename!="model.bin" else 60_000_000)


def verify_artifacts():
    expected = [
        AI/"ollama"/"ollama.exe",
        AI/"ollama"/"models"/"manifests"/"registry.ollama.ai"/"library"/"qwen3.5"/"0.8b",
        AI/"piper"/"piper.exe",
        AI/"piper"/"voices"/"fa_IR-amir-medium.onnx",
        AI/"piper"/"voices"/"fa_IR-amir-medium.onnx.json",
        AI/"whisper"/"base"/"model.bin",
        AI/"whisper"/"base"/"config.json",
    ]
    for file in expected:
        if not file.is_file():raise RuntimeError(f"Required bundled file missing: {file}")
    manifest=[]
    for file in sorted(AI.rglob("*")):
        if file.is_file():
            manifest.append({"path":str(file.relative_to(AI)).replace("\\","/"),
                             "bytes":file.stat().st_size,
                             "sha256":hashlib.file_digest(file.open("rb"),"sha256").hexdigest()})
    (ROOT/"embedded_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print("All bundled AI engines verified. Disk bytes:",sum(x["bytes"] for x in manifest),flush=True)


def main():
    DOWNLOADS.mkdir(parents=True,exist_ok=True)
    ollama=extract_ollama(download(OLLAMA_ZIP,DOWNLOADS/"ollama-windows-amd64.zip",minimum=100_000_000))
    extract_piper(download(PIPER_ZIP,DOWNLOADS/"piper_windows_amd64.zip",minimum=5_000_000))
    prepare_voices()
    prepare_whisper()
    pull_vision(ollama)
    verify_artifacts()


if __name__=="__main__":
    main()
