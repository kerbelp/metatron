"""A small stdlib HTTP server for the curation UI.

No web framework — `http.server` serves one HTML page plus JSON endpoints backed
by the same `PriorStore` the CLI uses. The request handler is a thin adapter over
the pure functions in :mod:`metatron.webui.api`.
"""

from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from metatron.storage.base import EventStore, PriorStore
from metatron.webui import api
from metatron.webui.observability import usage_summary

_INDEX_HTML = (Path(__file__).parent / "index.html").read_text()


def find_free_port(start: int = 1337, host: str = "127.0.0.1", attempts: int = 200) -> int:
    """Return the first bindable port at or after ``start``."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port found in {start}..{start + attempts}")


def make_server(
    store: PriorStore,
    host: str,
    port: int,
    event_store: EventStore | None = None,
    run_store=None,
) -> HTTPServer:
    return HTTPServer((host, port), _build_handler(store, event_store, run_store))


def serve(
    store: PriorStore,
    event_store: EventStore | None = None,
    host: str = "127.0.0.1",
    start_port: int = 1337,
    run_store=None,
) -> None:
    port = find_free_port(start=start_port, host=host)
    httpd = make_server(store, host, port, event_store, run_store)
    print(f"Metatron curation UI on http://{host}:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _build_handler(
    store: PriorStore, event_store: EventStore | None = None, run_store=None
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep output quiet
            pass

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            path = parts.path
            if path in ("/", "/index.html"):
                self._send_html(_INDEX_HTML)
            elif path == "/api/priors":
                self._send_json(_list(store, parse_qs(parts.query)))
            elif path == "/api/repos":
                self._send_json(api.repos(store))
            elif path == "/api/version":
                self._send_json(api.version())
            elif path == "/api/origins":
                self._send_json(
                    api.origin_breakdown(store, repo=_first(parse_qs(parts.query), "repo"))
                )
            elif path == "/api/feedback":
                repo = _first(parse_qs(parts.query), "repo")
                if event_store is not None:
                    self._send_json(api.feedback_analytics(event_store, store, repo=repo))
                else:
                    self._send_json({"priors": [], "by_origin": []})
            elif path == "/api/ingest-cost":
                repo = _first(parse_qs(parts.query), "repo")
                if run_store is not None:
                    self._send_json(api.ingest_cost(run_store, repo=repo))
                else:
                    self._send_json({"runs": []})
            elif path == "/api/stats":
                self._send_json(api.stats(store, repo=_first(parse_qs(parts.query), "repo")))
            elif path == "/api/usage":
                repo = _first(parse_qs(parts.query), "repo")
                if event_store is not None:
                    self._send_json(api.usage(event_store, store, repo=repo))
                else:
                    self._send_json(
                        {**usage_summary([]), "recent_queries": [], "recent_submissions": []}
                    )
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            segments = urlsplit(self.path).path.strip("/").split("/")
            # /api/priors/<id>/<action>
            if len(segments) == 4 and segments[:2] == ["api", "priors"]:
                prior_id, action = segments[2], segments[3]
                if action == "approve":
                    return self._send_json(api.approve(store, prior_id))
                if action == "reject":
                    return self._send_json(api.reject(store, prior_id))
            self._send_json({"error": "not found"}, status=404)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            self._respond(status, "application/json", json.dumps(payload).encode())

        def _send_html(self, html: str) -> None:
            self._respond(200, "text/html; charset=utf-8", html.encode())

        def _respond(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _first(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    value = query.get(key, [default])[0]
    return value or None


def _list(store: PriorStore, query: dict[str, list[str]]) -> dict:
    return api.list_priors(
        store,
        repo=_first(query, "repo"),
        status=_first(query, "status"),
        scope=_first(query, "scope"),
        triage=_first(query, "triage"),
        page=int(_first(query, "page") or "1"),
        page_size=int(_first(query, "page_size") or "20"),
    )
