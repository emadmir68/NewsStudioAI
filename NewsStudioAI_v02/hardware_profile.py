"""Automatic resource profiles for Windows CPU-only newsroom and dubbing workloads.

The 16 GB profile is tuned for Intel Core i5-12500 / UHD Graphics 770:
CPU Whisper int8, sequential vision and TTS, and bounded FFmpeg threads.
No dedicated NVIDIA GPU is assumed or required.
"""
from __future__ import annotations

import ctypes
import os
from functools import lru_cache


def installed_ram_gb() -> float:
    """Total physical RAM, without external packages. Returns 0 when unknown."""
    if os.name == "nt":
        try:
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            info = MemoryStatus()
            info.dwLength = ctypes.sizeof(info)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
                return round(info.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass
    else:
        try:
            with open("/proc/meminfo", encoding="utf-8") as handle:
                first = handle.readline()
            if first.startswith("MemTotal:"):
                return round(int(first.split()[1]) * 1024 / (1024 ** 3), 1)
        except Exception:
            pass
    return 0.0


def profile_for(ram_gb: float, logical_cpus: int) -> dict:
    """Pure configuration function, separately testable without model installs."""
    ram = max(0.0, float(ram_gb))
    cpus = max(1, int(logical_cpus))
    balanced = ram >= 14.0
    half_cpu = max(2, cpus // 2)
    return {
        "name": "balanced_16gb" if balanced else "light_cpu",
        "label_fa": "متعادل؛ ویژه رم ۱۶ گیگابایت" if balanced else "سبک؛ مناسب CPU و رم محدود",
        "installed_ram_gb": round(ram, 1),
        "logical_cpus": cpus,
        "device": "cpu",
        "compute_type": "int8",
        "whisper_model": "small" if balanced else "base",
        "whisper_threads": min(6 if balanced else 3, half_cpu),
        "vision_model": "qwen3-vl:2b",
        "vision_threads": min(6 if balanced else 3, half_cpu),
        "vision_context": 8192 if balanced else 4096,
        "frames": 48 if balanced else 30,
        "frame_width": 896 if balanced else 640,
        "tts_threads": min(4 if balanced else 2, half_cpu),
        "render_threads": min(4 if balanced else 2, half_cpu),
        "render_preset": "veryfast",
        "render_crf": 22 if balanced else 23,
        "sequential_ai": True,
        "uses_discrete_gpu": False,
    }


@lru_cache(maxsize=1)
def recommended_profile() -> dict:
    """A stable profile for the running session (can be audited via /api/health)."""
    return profile_for(installed_ram_gb(), os.cpu_count() or 2)
