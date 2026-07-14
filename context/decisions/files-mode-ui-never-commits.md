---
type: Metatron Decision
scope: metatron/webui
confidence: high
---

## Pattern
In files mode (`metatron ui --files`), every curation action is a git
working-tree operation — rewrite a concept file, `git mv` across status
directories, `git rm` — and the server never runs `git commit`. The human
reviews and lands all changes through the repository's normal git flow.

## Rationale
The canonical boundary must stay human-gated. If the UI committed, it would
become the curation act itself and bypass PR review; leaving changes staged in
the working tree makes git review the gate, which is the entire files-first
contract.
