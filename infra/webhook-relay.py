"""Dev only (`make webhook-tunnel`): let a real payment gateway (Razorpay test mode) reach the
local stack's webhook without exposing anything else.

POST /api/v1/webhooks/payments/... is forwarded to the web port unchanged (body and headers, so
the signature still matches); every other request gets 404. Tunnel this port, never the whole
app: the dev stack signs shops in with a fixed code."""

import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET = "http://localhost:3000"  # the web port; Next passes /api/* to the backend
PREFIX = "/api/v1/webhooks/payments/"
HOP = {"host", "connection", "content-length", "transfer-encoding", "accept-encoding"}


class Relay(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if not self.path.startswith(PREFIX):
            return self._send(404, b"not found")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        url = TARGET + self.path  # always http://localhost:3000/api/v1/webhooks/payments/...
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=20) as answer:  # noqa: S310
                status, text = answer.status, answer.read()
        except urllib.error.HTTPError as err:
            status, text = err.code, err.read()
        print(f"webhook {self.path[:60]}… -> {status} {text[:80]!r}", flush=True)
        return self._send(status, text)

    def do_GET(self) -> None:
        self._send(404, b"not found")

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass  # quiet: do_POST prints each webhook and its answer


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ThreadingHTTPServer(("127.0.0.1", port), Relay).serve_forever()
