"""A small stdlib HTTP server for the curation UI.

No web framework — `http.server` serves the static front-end (in ``app/``) plus JSON
endpoints backed by the same `DecisionStore` the CLI uses. The request handler is a thin
adapter over the pure functions in :mod:`metatron.webui.api`.
"""

from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from metatron.storage.base import EventStore, DecisionStore
from metatron.webui import api
from metatron.webui.jobs import FeedbackLoopJob, IngestJob, TriageJob
from metatron.webui.observability import usage_summary

# The built front-end (HTML/CSS/JSX/JS) lives here and is served as static files.
_APP_DIR = Path(__file__).parent / "app"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".jsx": "text/babel; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


def _content_type(name: str) -> str:
    return _CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream")


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
    store: DecisionStore,
    host: str,
    port: int,
    event_store: EventStore | None = None,
    run_store=None,
    refiner_factory=None,
    ingest_provider_factory=None,
) -> HTTPServer:
    return HTTPServer(
        (host, port),
        _build_handler(store, event_store, run_store, refiner_factory, ingest_provider_factory),
    )


def serve(
    store: DecisionStore,
    event_store: EventStore | None = None,
    host: str = "127.0.0.1",
    start_port: int = 1337,
    run_store=None,
    refiner_factory=None,
    ingest_provider_factory=None,
    open_browser: bool = True,
) -> None:
    port = find_free_port(start=start_port, host=host)
    httpd = make_server(
        store, host, port, event_store, run_store, refiner_factory, ingest_provider_factory
    )
    url = f"http://{host}:{port}"
    print(f"Metatron curation UI on {url}  (Ctrl-C to stop)")
    if open_browser:
        # Open the default browser once the server loop is up. A short timer avoids
        # racing serve_forever(); failures (headless/SSH) are non-fatal.
        import threading
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _build_handler(
    store: DecisionStore,
    event_store: EventStore | None = None,
    run_store=None,
    refiner_factory=None,
    ingest_provider_factory=None,
) -> type[BaseHTTPRequestHandler]:
    ingest_job = IngestJob(store, ingest_provider_factory, run_store)
    triage_job = TriageJob(store, ingest_provider_factory)
    feedback_loop_job = FeedbackLoopJob(
        store, event_store, refiner_factory, ingest_provider_factory
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep output quiet
            pass

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            path = parts.path
            if path in ("/", "/index.html"):
                self._send_file("index.html")
            elif path == "/api/decisions":
                self._send_json(_list(store, parse_qs(parts.query)))
            elif path == "/api/repos":
                self._send_json(api.repos(store))
            elif path.startswith("/api/decisions/"):
                decision = api.get_decision(store, path.split("/")[-1])
                self._send_json(decision or {"error": "not found"}, status=200 if decision else 404)
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
                    self._send_json({"decisions": [], "by_origin": []})
            elif path == "/api/leaderboard":
                repo = _first(parse_qs(parts.query), "repo")
                if event_store is not None:
                    self._send_json(api.leaderboard(event_store, store, repo=repo))
                else:
                    self._send_json({
                        "neutral": 5.5, "rated_total": 0, "review_count": 0,
                        "most_helpful": [], "misleading": [],
                    })
            elif path == "/api/feedback-events":
                query = parse_qs(parts.query)
                repo = _first(query, "repo")
                status = _first(query, "status") or "all"
                if event_store is not None:
                    self._send_json(
                        api.feedback_events(event_store, store, repo=repo, status=status)
                    )
                else:
                    self._send_json({"events": []})
            elif path == "/api/ingest-cost":
                repo = _first(parse_qs(parts.query), "repo")
                if run_store is not None:
                    self._send_json(api.ingest_cost(run_store, repo=repo))
                else:
                    self._send_json({"runs": []})
            elif path == "/api/ingest/status":
                self._send_json(ingest_job.status())
            elif path == "/api/valuate/status":
                self._send_json(triage_job.status())
            elif path == "/api/feedback/loop/status":
                self._send_json(feedback_loop_job.status())
            elif path == "/api/agent-activity":
                query = parse_qs(parts.query)
                repo = _first(query, "repo")
                window = int(_first(query, "window") or 30)
                if event_store is not None:
                    self._send_json(api.agent_activity(
                        event_store, store, repo=repo, window_mins=window))
                else:
                    self._send_json({"window_mins": window, "total_agents": 0,
                                     "total_served": 0, "total_feedback": 0, "agents": []})
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
            elif not path.startswith("/api/"):
                self._serve_static(path)
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            segments = urlsplit(self.path).path.strip("/").split("/")
            # /api/ingest/start — kick off a background ingest of a local repo
            if segments == ["api", "ingest", "start"]:
                body = self._read_json()
                return self._send_json(
                    ingest_job.start(body.get("path"), body.get("repo") or None)
                )
            # /api/feedback/loop/start — refine all unhandled feedback, valuate the
            # resulting candidates, then approve the recommended ones (one-click loop)
            if segments == ["api", "feedback", "loop", "start"]:
                body = self._read_json()
                return self._send_json(feedback_loop_job.start(body.get("repo") or None))
            # /api/valuate/start — run the advisory judge over a repo's candidates,
            # optionally scoped by origin and approving the winners (one-click loop)
            if segments == ["api", "valuate", "start"]:
                body = self._read_json()
                return self._send_json(triage_job.start(
                    body.get("repo") or None,
                    origin=body.get("origin") or None,
                    approve_after=bool(body.get("approve")),
                ))
            # /api/decisions — create a human-authored candidate
            if segments == ["api", "decisions"]:
                body = self._read_json()
                return self._send_json(api.create_decision(store, body))
            # /api/decisions/approve-recommended — one-click bulk approve of "approve" picks
            if segments == ["api", "decisions", "approve-recommended"]:
                body = self._read_json()
                return self._send_json(api.approve_recommended(
                    store, repo=body.get("repo") or None, origin=body.get("origin") or None
                ))
            # /api/decisions/<id>/<action>
            if len(segments) == 4 and segments[:2] == ["api", "decisions"]:
                decision_id, action = segments[2], segments[3]
                if action == "approve":
                    return self._send_json(api.approve(store, decision_id))
                if action == "reject":
                    return self._send_json(api.reject(store, decision_id))
                if action == "valuate":
                    return self._send_json(
                        api.valuate_one(store, ingest_provider_factory, decision_id)
                    )
                if action == "update":
                    body = self._read_json()
                    return self._send_json(api.update_decision(store, decision_id, body))
            # /api/feedback/<id>/refine — run the LLM refiner on one feedback event
            if (
                len(segments) == 4
                and segments[:2] == ["api", "feedback"]
                and segments[3] == "refine"
            ):
                return self._send_json(
                    api.refine_one(store, event_store, refiner_factory, segments[2])
                )
            self._send_json({"error": "not found"}, status=404)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode() or "{}")
            except (ValueError, UnicodeDecodeError):
                return {}

        def _send_json(self, payload: dict, status: int = 200) -> None:
            self._respond(status, "application/json", json.dumps(payload).encode())

        def _send_file(self, name: str) -> None:
            self._respond(200, _content_type(name), (_APP_DIR / name).read_bytes())

        def _serve_static(self, path: str) -> None:
            # The app dir is flat; reject any nesting/traversal and serve only real files.
            name = path.lstrip("/")
            target = _APP_DIR / name
            if "/" in name or not target.is_file() or target.parent != _APP_DIR:
                return self._send_json({"error": "not found"}, status=404)
            self._respond(200, _content_type(name), target.read_bytes())

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


def _list(store: DecisionStore, query: dict[str, list[str]]) -> dict:
    return api.list_decisions(
        store,
        repo=_first(query, "repo"),
        status=_first(query, "status"),
        scope=_first(query, "scope"),
        triage=_first(query, "triage"),
        origin=_first(query, "origin"),
        search=_first(query, "search"),
        page=int(_first(query, "page") or "1"),
        page_size=int(_first(query, "page_size") or "20"),
    )
