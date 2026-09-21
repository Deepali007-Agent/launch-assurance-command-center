"""Authenticated local intake API for connected intelligence agents."""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from orchestration.intake import PublicationStore


class Handler(BaseHTTPRequestHandler):
    store = PublicationStore()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = os.getenv("RETAIL_PLATFORM_API_TOKEN", "")
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return bool(expected) and hmac.compare_digest(expected, supplied)

    def do_POST(self):
        if urlparse(self.path).path != "/v1/publications":
            return self._json(404, {"error": "Not found"})
        if not self._authorized():
            return self._json(401, {"error": "Invalid or missing bearer token"})
        publication_id = self.headers.get("Idempotency-Key", "").strip()
        if not publication_id:
            return self._json(400, {"error": "Idempotency-Key is required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            acknowledgement = self.store.receive(publication_id, payload)
            self._json(202, acknowledgement)
        except (ValueError, json.JSONDecodeError) as error:
            self._json(422, {"error": str(error)})
        except Exception as error:
            self._json(500, {"error": f"Publication intake failed: {error}"})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, self.store.health_summary())
        if path.startswith("/v1/publications/"):
            if not self._authorized():
                return self._json(401, {"error": "Invalid or missing bearer token"})
            publication = self.store.get(path.rsplit("/", 1)[-1])
            return self._json(200, publication) if publication else self._json(404, {"error": "Unknown publication"})
        self._json(404, {"error": "Not found"})

    def log_message(self, format, *args):
        return


def run() -> None:
    host = os.getenv("RETAIL_PLATFORM_API_HOST", "127.0.0.1")
    port = int(os.getenv("RETAIL_PLATFORM_API_PORT", "8511"))
    if not os.getenv("RETAIL_PLATFORM_API_TOKEN"):
        raise RuntimeError("RETAIL_PLATFORM_API_TOKEN must be configured before starting the intake API.")
    print(f"Retail Intelligence intake API listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run()
