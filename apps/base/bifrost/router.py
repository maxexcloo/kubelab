"""Serves Bifrost's local/ provider from Radiance, and lists cloud/'s aliases.

Radiance loads the model a request names, so local/<name> reaches Radiance as <name>; auto and
uncensored are Radiance aliases. Radiance also serves image and video models, so only the text
models in LOCAL are listed and served. Requests otherwise pass through unchanged, so clients set
reasoning themselves. A request whose model is not on the cards within LOAD_WAIT seconds, such as
while a video holds them, or any while Radiance is stopped, fails with 503 and nothing falls back.
"""

import http.client
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ALIASES = {
    "cloud": (
        "auto",
        "deepseek-flash",
        "deepseek-flash-uncensored",
        "glm",
        "glm-flash",
        "glm-flash-uncensored",
        "glm-uncensored",
        "mimo",
        "mimo-flash",
        "uncensored",
    ),
    "local": ("auto", "uncensored"),
}
HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "transfer-encoding",
}
# Normal cold loads take up to about 30 s.
LOAD_WAIT = 60
# The text entries of apps/base/radiance/radiance.yaml.
LOCAL = (
    "gemma-4-31b-heretic",
    "qwen3.8-27b-iq4r",
    "qwen3.8-27b-uncensored",
    "qwen3.8-flash-next",
)
PORT = int(os.environ["PORT"])
RADIANCE = urlsplit(os.environ["RADIANCE_URL"])


def radiance(timeout=None):
    return http.client.HTTPConnection(RADIANCE.hostname, RADIANCE.port, timeout=timeout)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, {"status": "ok"})
        if self.path == "/local/v1/models":
            data = [{"id": alias, "object": "model"} for alias in ALIASES["local"]]
            upstream = radiance(timeout=5)
            try:
                upstream.request("GET", "/v1/models", headers=self.forwarded())
                response = upstream.getresponse()
                if response.status == 200:
                    data += [m for m in json.load(response)["data"] if m["id"] in LOCAL]
            except OSError:
                pass
            finally:
                upstream.close()
            return self.reply(200, {"data": data, "object": "list"})
        # Bifrost's cloud routing rules send cloud/ on before it reaches the router.
        provider = self.path.removeprefix("/").removesuffix("/v1/models")
        if provider == "cloud":
            data = [{"id": alias, "object": "model"} for alias in ALIASES[provider]]
            return self.reply(200, {"data": data, "object": "list"})
        self.reply(404, {"error": {"message": f"{self.path} is not served"}})

    def do_POST(self):
        provider, _, path = self.path.removeprefix("/").partition("/")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        model = json.loads(body).get("model")
        message = f"no running model serves {provider}/{model}"
        if provider == "local" and model in ALIASES["local"] + LOCAL:
            upstream = radiance()
            try:
                upstream.connect()
            except OSError:
                upstream = None
            if upstream:
                # Radiance holds a request while it loads the model, up to its load-timeout,
                # and generation can take minutes.
                upstream.sock.settimeout(None)
                upstream.request("POST", f"/{path}", body, self.forwarded())
                if self.loaded(model):
                    return self.relay(upstream.getresponse(), upstream)
                # Radiance still loads the model for the abandoned request.
                upstream.close()
                message = f"{provider}/{model} did not load within {LOAD_WAIT} s; Radiance's cards are probably busy"
        self.reply(503, {"error": {"message": message, "type": "service_unavailable"}})

    def loaded(self, model):
        """Whether the model comes onto the cards within LOAD_WAIT; a failed lookup does not wait."""
        deadline = time.monotonic() + LOAD_WAIT
        while time.monotonic() < deadline:
            upstream = radiance(timeout=5)
            try:
                upstream.request("GET", "/v1/models", headers=self.forwarded())
                response = upstream.getresponse()
                entries = json.load(response)["data"] if response.status == 200 else []
                state = next((m["state"] for m in entries if m["id"] == model), None)
            except OSError:
                state = None
            finally:
                upstream.close()
            # Radiance answers a failed load itself.
            if state in (None, "failed", "resident"):
                return True
            time.sleep(1)
        return False

    def forwarded(self):
        return {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}

    def relay(self, response, upstream):
        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() not in HOP_HEADERS:
                self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        # Stream as it arrives so server-sent events are not held back.
        while chunk := response.read1(65536):
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        upstream.close()

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_request(self, code="-", size="-"):
        if self.path != "/healthz":
            super().log_request(code, size)


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
