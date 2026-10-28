"""Routes Bifrost's local/ models to the local text models.

local/text and the thinking levels reach the first running model in MODELS, moving on
when one is stopped or full; local/<model> reaches that model alone. Levels set the
request's reasoning fields; everything else passes through. Model lists name only
running models, and requests nothing can serve fail fast with 503. Bifrost's cloud/
provider reaches /cloud/..., forwarded to CLOUD_URL with the key Bifrost sends: the
shared names use CLOUD_MODEL, and any other name is the provider's own model.
"""

import http.client
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BUDGET_FIELDS = (
    "reasoning_budget_tokens",
    "thinking_budget",
    "thinking_budget_tokens",
    "thinking_token_budget",
)
# Fields a level replaces, so a client's own setting cannot contradict the name.
THINKING_FIELDS = ("reasoning", "reasoning_effort", *BUDGET_FIELDS)
# Budgets cap thinking on templates that only switch it on or off.
LEVELS = {
    "high": {"reasoning_effort": "high"},
    "low": {"reasoning_effort": "low", "thinking_budget_tokens": 1024},
    "medium": {"reasoning_effort": "medium", "thinking_budget_tokens": 4096},
    "off": {"reasoning_effort": "none"},
}
# Text Services in order of preference.
MODELS = (
    "maya",
    "qwen-flash-next",
    "qwen-fp8",
    "qwen-mxfp4",
    "gemma",
    "qwen-35b",
    "gemma-26b",
)
SHARED = ("text", *LEVELS)
# Radiance answers 429 when its queue is full, and 503 while busy or reloading.
BUSY = {429, 503}
HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "transfer-encoding",
}
CLOUD_MODEL = os.environ["CLOUD_MODEL"]
CLOUD_URL = urllib.parse.urlsplit(os.environ["CLOUD_URL"])
PORT = int(os.environ["PORT"])
UPSTREAM = os.environ["UPSTREAM"]


def connect(model):
    upstream = http.client.HTTPConnection(UPSTREAM.format(model), timeout=5)
    try:
        upstream.connect()
    except OSError:
        return None
    # Generation can take minutes once connected.
    upstream.sock.settimeout(None)
    return upstream


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, {"status": "ok"})
        if self.path in ("/cloud/v1/models", "/v1/models"):
            cloud = self.path.startswith("/cloud/")
            names = (*SHARED, *self.cloud_models()) if cloud else running()
            return self.reply(
                200,
                {
                    "data": [{"id": name, "object": "model"} for name in names],
                    "object": "list",
                },
            )
        self.reply(404, {"error": {"message": f"{self.path} is not served"}})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        model = json.loads(body).get("model")
        cloud = self.path.startswith("/cloud/")
        if not cloud and model not in (*SHARED, *MODELS):
            return self.reply(
                404,
                {
                    "error": {
                        "message": f"unknown model {model}",
                        "type": "invalid_request_error",
                    }
                },
            )
        if model in LEVELS:
            body = apply_level(body)
        if cloud:
            if model in SHARED:
                request = json.loads(body) | {"model": CLOUD_MODEL}
                # Abliteration grades effort itself and rejects medium with a budget.
                for field in BUDGET_FIELDS:
                    request.pop(field, None)
                body = json.dumps(request).encode()
            upstream, response = self.cloud("POST", self.path, body)
            return self.relay(response, upstream)
        candidates = MODELS if model in SHARED else (model,)
        for index, candidate in enumerate(candidates):
            if (upstream := connect(candidate)) is None:
                continue
            upstream.request("POST", self.path, body, self.forwarded())
            response = upstream.getresponse()
            if response.status in BUSY and index < len(candidates) - 1:
                upstream.close()
                continue
            return self.relay(response, upstream)
        message = (
            "no local text model is running"
            if model in SHARED
            else f"{model} is not running"
        )
        self.reply(503, {"error": {"message": message, "type": "service_unavailable"}})

    def forwarded(self):
        return {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}

    def cloud(self, method, path, body=None):
        upstream = http.client.HTTPSConnection(CLOUD_URL.netloc)
        path = CLOUD_URL.path + path.removeprefix("/cloud")
        upstream.request(method, path, body, self.forwarded())
        return upstream, upstream.getresponse()

    def cloud_models(self):
        upstream, response = self.cloud("GET", self.path)
        listing = (
            json.loads(response.read()) if response.status == 200 else {"data": []}
        )
        upstream.close()
        return [model["id"] for model in listing["data"]]

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


def apply_level(body):
    request = json.loads(body)
    for field in THINKING_FIELDS:
        request.pop(field, None)
    if isinstance(request.get("chat_template_kwargs"), dict):
        request["chat_template_kwargs"].pop("enable_thinking", None)
        request["chat_template_kwargs"].pop("reasoning_effort", None)
    return json.dumps(request | LEVELS[request["model"]]).encode()


def running():
    models = []
    for model in MODELS:
        if upstream := connect(model):
            upstream.close()
            models.append(model)
    return [*SHARED, *models] if models else []


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
