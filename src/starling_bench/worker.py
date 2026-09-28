"""A supervised native server process with controller-owned HTTP timing."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from starling_bench.artifacts import BenchError, sha256
from starling_bench.models import Arm, Spec

MAX_RESPONSE_BYTES = 1_000_000


def stage(arm: Arm, directory: Path) -> None:
    directory.mkdir(parents=True)
    for artifact in (arm.binary, *arm.runtime_files):
        destination = directory / Path(artifact.path).name
        shutil.copy2(artifact.path, destination)
        if sha256(destination) != artifact.sha256:
            raise BenchError(f"artifact changed during staging: {artifact.path}")


class Server:
    def __init__(self, spec: Spec, arm: Arm, directory: Path, log_path: Path):
        self.spec, self.arm, self.directory, self.log_path = spec, arm, directory, log_path
        self.proc = None
        self.log = None
        # Ignore HTTP proxy environment variables for loopback requests.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __enter__(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        home = self.log_path.parent / (self.log_path.stem + "-home")
        home.mkdir()
        env = {
            "PATH": os.defpath,
            "HOME": str(home),
            "TMPDIR": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "LD_LIBRARY_PATH": str(self.directory),
            "STARLING_ENGINE": "ggml",
            "STARLING_GGML_DEVICE": {"cpu": "cpu", "cuda": "CUDA0", "vulkan": "Vulkan0"}[
                self.spec.device.backend
            ],
            **self.arm.env,
        }
        if self.spec.kind == "synthetic":
            scripts = [p for p in self.arm.runtime_files if Path(p.path).name == "demo_server.py"]
            if len(scripts) != 1:
                raise BenchError("synthetic arm requires a pinned demo_server.py runtime file")
            cmd = [self.arm.binary.path, str(self.directory / "demo_server.py")]
        else:
            cmd = [str(self.directory / Path(self.arm.binary.path).name)]
        cmd += [
            "--model",
            self.spec.model_slug,
            "--gguf",
            self.spec.model.path,
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]
        self.log = self.log_path.open("wb")
        started = time.perf_counter_ns()
        try:
            self.proc = subprocess.Popen(
                cmd,
                env=env,
                cwd=home,
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + self.spec.protocol.startup_timeout_s
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise BenchError(f"server exited during startup; see {self.log_path.name}")
                try:
                    with self.http.open(self.base_url + "/health", timeout=0.3) as reply:
                        health = json.loads(reply.read(MAX_RESPONSE_BYTES))
                    if health.get("loaded") is True and health.get("model") == self.spec.model_slug:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.05)
            else:
                raise BenchError("server startup deadline exceeded")
            self.startup_ms = (time.perf_counter_ns() - started) / 1e6
            log = self.log_path.read_text(errors="replace")
            matches = re.findall(
                r"\[starling-serve\] starting on .*\(model=[^,]+, backend=([^,]+), abi=\d+\)",
                log,
            )
            self.backend = matches[-1].lower() if matches else "unknown"
            if not re.fullmatch(re.escape(self.spec.device.backend) + r"\d*", self.backend):
                raise BenchError(
                    f"backend mismatch: expected {self.spec.device.backend}, got {self.backend}"
                )
            return self
        except BaseException:
            self.stop()
            raise

    def transcribe(self, audio: bytes) -> tuple[float, str]:
        boundary = uuid.uuid4().hex
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
                f"{self.spec.model_slug}\r\n--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="input.wav"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode()
            + audio
            + f"\r\n--{boundary}--\r\n".encode()
        )
        request = urllib.request.Request(
            self.base_url + "/v1/audio/transcriptions",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        started = time.perf_counter_ns()
        try:
            with self.http.open(request, timeout=self.spec.protocol.request_timeout_s) as reply:
                payload = reply.read(MAX_RESPONSE_BYTES + 1)
            elapsed = (time.perf_counter_ns() - started) / 1e6
            if len(payload) > MAX_RESPONSE_BYTES:
                raise BenchError("transcription response exceeds size limit")
            value = json.loads(payload)
            if not isinstance(value, dict) or not isinstance(value.get("text"), str):
                raise BenchError("transcription response must contain a string text field")
            return elapsed, value["text"]
        except (OSError, ValueError) as exc:
            raise BenchError(f"transcription failed: {type(exc).__name__}: {exc}") from exc

    def stop(self) -> None:
        if self.proc:
            # Kill the process group even if its leader exited; descendants may survive it.
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait(timeout=2)
        if self.log:
            self.log.close()

    def __exit__(self, *args):
        self.stop()
