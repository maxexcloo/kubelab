"""Serves Bifrost's ai/ and local/ providers from the text Services, and lists cloud/auto.

Each Service in NAMESPACE annotated text.excloo.dev/priority serves one local text model.
ai/ lists the running ones under the names they report and reaches each by name; local/auto
reaches them in priority order, moving on when one is busy. Requests otherwise pass through
unchanged, so clients set reasoning themselves. Requests nothing can serve fail fast with 503.
"""

import http.client
import json
import os
import ssl
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCOUNT = "/var/run/secrets/kubernetes.io/serviceaccount"
API = "https://kubernetes.default.svc"
# Radiance answers 429 when its queue is full, and 503 while busy or reloading.
BUSY = {429, 503}
HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "transfer-encoding",
}
NAMESPACE = os.environ["NAMESPACE"]
PORT = int(os.environ["PORT"])


def kubernetes(path):
    with open(f"{ACCOUNT}/token", encoding="utf-8") as token:
        headers = {"Authorization": f"Bearer {token.read()}"}
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    context = ssl.create_default_context(cafile=f"{ACCOUNT}/ca.crt")
    with urllib.request.urlopen(request, context=context, timeout=5) as response:
        return json.load(response)["items"]


def running(headers):
    """Each running Service, in priority order, with the models it reports."""
    slices = kubernetes(
        f"/apis/discovery.k8s.io/v1/namespaces/{NAMESPACE}/endpointslices"
    )
    ready = {
        item["metadata"]["labels"]["kubernetes.io/service-name"]
        for item in slices
        if any(e["conditions"].get("ready") for e in item.get("endpoints") or [])
    }
    services = sorted(
        (int(priority), item["metadata"]["name"])
        for item in kubernetes(f"/api/v1/namespaces/{NAMESPACE}/services")
        if (
            priority := item["metadata"]
            .get("annotations", {})
            .get("text.excloo.dev/priority")
        )
        and item["metadata"]["name"] in ready
    )
    found = []
    for _, service in services:
        upstream = http.client.HTTPConnection(
            f"{service}.{NAMESPACE}.svc", 8000, timeout=5
        )
        try:
            upstream.request("GET", "/v1/models", headers=headers)
            response = upstream.getresponse()
            if response.status == 200:
                found.append((service, json.load(response)["data"]))
        except OSError:
            pass
        finally:
            upstream.close()
    return found


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, {"status": "ok"})
        if self.path == "/ai/v1/models":
            data = [
                model for _, models in running(self.forwarded()) for model in models
            ]
            return self.reply(200, {"data": data, "object": "list"})
        # Bifrost's cloud routing rule sends cloud/auto on before it reaches the router.
        if self.path in ("/cloud/v1/models", "/local/v1/models"):
            data = [{"id": "auto", "object": "model"}]
            return self.reply(200, {"data": data, "object": "list"})
        self.reply(404, {"error": {"message": f"{self.path} is not served"}})

    def do_POST(self):
        provider, _, path = self.path.removeprefix("/").partition("/")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        model = body.get("model")
        served = [
            (service, models[0]["id"] if model == "auto" else model)
            for service, models in running(self.forwarded())
            if (provider == "local" and model == "auto" and models)
            or (provider == "ai" and any(m["id"] == model for m in models))
        ]
        for index, (service, name) in enumerate(served):
            upstream = http.client.HTTPConnection(f"{service}.{NAMESPACE}.svc", 8000)
            try:
                upstream.connect()
            except OSError:
                continue
            # Generation can take minutes once connected.
            upstream.sock.settimeout(None)
            data = json.dumps(body | {"model": name}).encode()
            upstream.request("POST", f"/{path}", data, self.forwarded())
            response = upstream.getresponse()
            if response.status in BUSY and index < len(served) - 1:
                upstream.close()
                continue
            return self.relay(response, upstream)
        message = f"no running model serves {provider}/{model}"
        self.reply(503, {"error": {"message": message, "type": "service_unavailable"}})

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
