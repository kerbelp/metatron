---
type: Metatron Decision
scope: metatron/webui
confidence: high
source_refs:
  - metatron/webui/server.py
  - metatron/webui/api.py
---

## Pattern
The curation web UI server uses only the stdlib (`http.server`) — no Flask,
FastAPI, or any web framework. The request handler is a thin adapter; endpoint
logic lives in `webui/api.py` as pure functions that take stores and return
JSON-serializable dicts.

## Rationale
The UI is a local, single-user view over the same `DecisionStore` the CLI uses;
a framework would add a dependency and a deployment surface for no benefit
(hosted/multi-user is explicitly out of scope). Pure api-functions keep endpoint
logic testable without spinning up a server.
