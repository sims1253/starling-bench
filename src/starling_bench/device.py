"""Local Linux identity, cooperative exclusive leases, and best-effort telemetry."""

from __future__ import annotations

import contextlib
import fcntl
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from starling_bench.artifacts import BenchError, digest
from starling_bench.models import Device


def inventory(backend: str) -> dict:
    if platform.system() != "Linux":
        raise BenchError("v0.1 workers require Linux; run the worker on the target Linux host")
    cpu = "unknown"
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    machine = Path("/etc/machine-id")
    info = {
        "system": platform.system(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu": cpu,
        "host_id_sha256": digest(machine.read_text().strip()) if machine.exists() else None,
        "backend": backend,
    }
    if backend == "cuda":
        cmd = ["nvidia-smi", "--query-gpu=uuid,name,driver_version", "--format=csv,noheader"]
    elif backend == "vulkan":
        cmd = ["vulkaninfo", "--summary"]
    else:
        cmd = None
    if cmd:
        if not shutil.which(cmd[0]):
            raise BenchError(f"{cmd[0]} is required to identify the {backend} device")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode or not result.stdout.strip():
            raise BenchError(f"{cmd[0]} could not identify the device")
        info["accelerators"] = result.stdout.strip()
    return info


def identify(label: str, backend: str) -> Device:
    info = inventory(backend)
    return Device(label=label, backend=backend, fingerprint=digest(info), observations=info)


def telemetry() -> dict:
    temperatures = {}
    for sensor in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            temperatures[sensor.parent.name] = int(sensor.read_text()) / 1000
        except (OSError, ValueError):
            continue
    return {"load_average": list(os.getloadavg()), "temperatures_c": temperatures}


@contextlib.contextmanager
def lease():
    # One host-wide lease prevents CPU compilation and GPU trials from competing.
    # Labels and spec fingerprints cannot be used to evade this lock.
    root = Path(tempfile.gettempdir()) / f"starling-bench-{os.getuid()}"
    root.mkdir(mode=0o700, exist_ok=True)
    with (root / "host.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BenchError("this host already has an active Starling Bench measurement") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
