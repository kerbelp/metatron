---
type: Metatron Decision
scope: metatron/webui
confidence: high
---

## Pattern
When smoke-testing the web UI locally, kill stale servers by port
(`kill $(lsof -tiTCP:<port> -sTCP:LISTEN)`) before relaunching, and verify
which process owns the port afterwards — never rely only on matching the
launcher's command line.

## Rationale
`find_free_port` silently bumps to the next port when the requested one is
taken, so a stale server keeps answering on the expected port while the new
build listens elsewhere — probes then hit old code and produce phantom 404s.
Servers launched via stdin heredocs also evade `pkill -f <script>` patterns.
