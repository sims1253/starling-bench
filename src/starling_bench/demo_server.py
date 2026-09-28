"""SYNTHETIC protocol fixture. This program performs no speech inference."""

import argparse
import io
import json
import os
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TEXTS = ("a small bird sings", "the notebook is ready", "measure every attempt")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--gguf")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, value):
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.send_json({"model": args.model, "loaded": True})

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            wav_start = body.find(b"RIFF")
            with wave.open(io.BytesIO(body[wav_start:]), "rb") as wav:
                index = int.from_bytes(wav.readframes(1), "little", signed=True)
            delay = float(os.environ.get("STARLING_BENCH_DEMO_DELAY_MS", "10"))
            time.sleep(delay / 1000)
            text = "wrong output" if os.environ.get("STARLING_BENCH_DEMO_WRONG") else TEXTS[index]
            self.send_json({"text": text, "latency_ms": 0.000001})  # Ignored by the controller.

    backend = os.environ.get("STARLING_BENCH_DEMO_BACKEND", "cpu")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"[starling-serve] starting on {args.host}:{args.port} "
        f"(model={args.model}, backend={backend}, abi=1)",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
