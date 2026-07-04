---
type: Metatron Decision
scope: metatron/mcp_server
confidence: high
source_refs:
  - metatron/mcp_server/service.py
  - metatron/mcp_server/server.py
---

## Pattern
Retrieval and submission logic lives in `mcp_server/service.py` as plain
functions taking a store, independent of the MCP SDK; `server.py` is a thin
adapter that registers tools and delegates. New tool behavior goes in the
service layer with direct unit tests — never inline in tool handlers.

## Rationale
MCP handlers are awkward to test through the protocol. Keeping the logic pure
(store in, decisions out) makes ranking changes testable with in-memory stores
and keeps the SDK dependency at the edge.
