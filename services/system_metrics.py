#!/usr/bin/env python3
"""System metrics collection helpers."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

# 台灣時區 (UTC+8)
TAIWAN_TZ = timezone(timedelta(hours=8))
_CPU_USAGE_PREV = {"total": None, "idle": None}


def now_taiwan():
    """獲取台灣時間"""
    return datetime.now(TAIWAN_TZ)


def _read_cpu_usage_percent():
    """從 /proc/stat 計算 CPU 使用率（百分比）"""
    global _CPU_USAGE_PREV
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        parts = first_line.split()
        if len(parts) < 8 or parts[0] != "cpu":
            return None

        values = [int(v) for v in parts[1:8]]
        idle = values[3] + values[4]
        total = sum(values)

        prev_total = _CPU_USAGE_PREV["total"]
        prev_idle = _CPU_USAGE_PREV["idle"]
        _CPU_USAGE_PREV = {"total": total, "idle": idle}

        if prev_total is None or prev_idle is None:
            if total <= 0:
                return None
            return round(max(0.0, min(100.0, (1 - (idle / total)) * 100.0)), 1)

        total_diff = total - prev_total
        idle_diff = idle - prev_idle
        if total_diff <= 0:
            return None

        usage = (1.0 - (idle_diff / total_diff)) * 100.0
        return round(max(0.0, min(100.0, usage)), 1)
    except Exception:
        return None


def _read_ram_usage_percent():
    """從 /proc/meminfo 計算 RAM 使用率（百分比）"""
    try:
        mem_total = None
        mem_available = None
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1])

        if not mem_total or mem_available is None:
            return None

        used = mem_total - mem_available
        if mem_total <= 0:
            return None

        return round(max(0.0, min(100.0, (used / mem_total) * 100.0)), 1)
    except Exception:
        return None


def _read_cpu_temp_c():
    """讀取 CPU 溫度（攝氏）"""
    candidates = [
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/devices/virtual/thermal/thermal_zone0/temp"),
    ]
    for path in candidates:
        try:
            if path.exists():
                raw = path.read_text(encoding="utf-8").strip()
                value = float(raw) / 1000.0
                return round(value, 1)
        except Exception:
            continue
    return None


def get_system_metrics():
    """讀取樹莓派系統資訊"""
    return {
        "cpu_usage_percent": _read_cpu_usage_percent(),
        "ram_usage_percent": _read_ram_usage_percent(),
        "temperatures_c": {
            "cpu": _read_cpu_temp_c(),
        },
        "timestamp": now_taiwan().isoformat(),
    }

