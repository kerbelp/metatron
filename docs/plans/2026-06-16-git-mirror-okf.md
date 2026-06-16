# Git-backed Decision Mirror + OKF Export — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror Metatron's candidate/canonical decisions to a git-tracked markdown bundle inside the consuming repo (audit + file-first editing), emit that bundle as a valid OKF bundle, and round-trip human edits back into the authoritative SQLite store.

**Architecture:** SQLite stays authoritative. A new `metatron/mirror/` package renders decisions to markdown+frontmatter (export), parses them back applying only human-owned fields with directory-as-status (import), and lays the same files out as an OKF bundle. A new `mirror` CLI subcommand group drives both directions explicitly. No watcher/auto-sync in v1.

**Tech Stack:** Python 3.12, pydantic models (`metatron/models.py`), argparse CLI (`metatron/cli.py`), PyYAML for frontmatter, pytest. Reuses `metatron/feedback_score.py` (`helpfulness_scores`) and the `DecisionStore` interface.

**Design doc:** `docs/designs/2026-06-16-git-mirror-okf.md`

---

## File Structure

**New package `metatron/mirror/`:**
- `metatron/mirror/__init__.py` — package exports.
- `metatron/mirror/render.py` — pure (de)serialization: `Decision` ⇄ markdown document (YAML frontmatter + body). Knows the field-ownership split and which fields are read-only. No I/O.
- `metatron/mirror/layout.py` — pure path/identity helpers: stable `slug_for(decision)`, `path_for(decision)` (`candidate/` vs `decisions/`), and `status_for_path(path)` (directory → `Status`).
- `metatron/mirror/export.py` — DB → bundle on disk: writes one file per `candidate`/`canonical` decision, the read-only feedback summary block, and a `.sync-state.json` of per-id content hashes. Side-effectful, thin over `render`/`layout`.
- `metatron/mirror/sync_import.py` — bundle → DB: parse files, map directory→status, diff human-owned fields, guard machine-owned fields, detect collisions against `.sync-state.json`. Returns a structured diff; applies via the store.
- `metatron/mirror/okf.py` — OKF v0.1 bundle manifest + layout + structural validation, reusing rendered documents from `render`.

**Modified:**
- `metatron/cli.py` — add a `mirror` subcommand group (`sync` / `import`, `--okf`) and `_cmd_mirror`, alongside existing `repo`/`candidates` groups. Do **not** touch the existing top-level `export`/`import` (DB-catalog transfer).
- `pyproject.toml` — add `pyyaml` to dependencies if not already present (verify first).

**New tests:**
- `tests/test_mirror_render.py`, `tests/test_mirror_layout.py`, `tests/test_mirror_export.py`, `tests/test_mirror_import.py`, `tests/test_mirror_okf.py`, `tests/test_cli_mirror.py`.

**Conventions to follow:**
- TDD per @superpowers:test-driven-development; fixtures in `tests/conftest.py` (autouse store isolation already exists).
- Field-ownership table and read-only rules come straight from the design doc — do not let machine-owned fields round-trip.
- Public-facing copy stays neutral and product-focused.

---

### Task 0: Confirm dependency + package skeleton

**Files:**
- Modify: `pyproject.toml` (only if `pyyaml` missing)
- Create: `metatron/mirror/__init__.py`

- [ ] **Step 1: Check whether PyYAML is already available**

Run: `cd /Users/pavel/dev/getmetatron/metatron/.worktrees/git-mirror-okf && uv run python -c "import yaml; print(yaml.__version__)"`
Expected: a version string (already a transitive dep) OR `ModuleNotFoundError`.

- [ ] **Step 2: If missing, add it**

Add `"pyyaml>=6.0"` to `[project].dependencies` in `pyproject.toml`, then `uv sync`. Skip if Step 1 printed a version.

- [ ] **Step 3: Create the empty package**

```python
# metatron/mirror/__init__.py
"""Git-backed markdown mirror of decisions, and OKF bundle export.

SQLite stays authoritative; this package renders decisions to a git-tracked
bundle (export), parses human edits back applying only human-owned fields
(import), and lays the same files out as an Open Knowledge Format bundle.
"""
```

- [ ] **Step 4: Commit**

```bash
git add metatron/mirror/__init__.py pyproject.toml uv.lock
git commit -m "feat(mirror): scaffold mirror package"
```

---

### Task 1: Render — Decision → markdown document

**Files:**
- Create: `metatron/mirror/render.py`
- Test: `tests/test_mirror_render.py`

- [ ] **Step 1: Write the failing test (serialize)**

```python
# tests/test_mirror_render.py
from metatron.models import Decision, Origin, Confidence, SourceRef, SourceRefKind
from metatron.mirror.render import render_document

def _decision(**kw):
    base = dict(repo="github.com/acme/app", pattern="Use zod at API boundaries",
                scope="web/api", rationale="Hand-rolled validation drifts.",
                origin=Origin.AGENT_SUBMITTED, confidence=Confidence.MEDIUM,
                keywords=["zod", "validation"],
                source_refs=[SourceRef(kind=SourceRefKind.FILE, ref="src/api/validate.ts:42")])
    base.update(kw); return Decision(**base)

def test_render_includes_human_fields_in_frontmatter_and_body():
    text = render_document(_decision(), helpfulness=None)
    assert "id:" in text and "confidence: medium" in text
    assert "Use zod at API boundaries" in text          # pattern in body
    assert "Hand-rolled validation drifts." in text     # rationale in body
    assert "src/api/validate.ts:42" in text             # source_refs

def test_render_marks_machine_fields_readonly():
    text = render_document(_decision(), helpfulness=None)
    # keywords are machine-owned: present but flagged read-only
    assert "keywords:" in text
    assert "read-only" in text.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mirror_render.py -q`
Expected: FAIL — `ModuleNotFoundError: metatron.mirror.render`.

- [ ] **Step 3: Implement `render_document`**

```python
# metatron/mirror/render.py
"""Pure (de)serialization between a Decision and its markdown mirror document.

A document is YAML frontmatter (identity + human-owned scalar fields + read-only
machine fields) plus a markdown body (pattern, rationale, source refs, and a
read-only feedback summary). Read-only fields are emitted so the audit/diff shows
them, but `parse_document` never returns them as editable.
"""
from __future__ import annotations

import yaml
from metatron.models import Decision
from metatron.feedback_score import HelpfulnessScore

# Fields a human edit is allowed to change (see design doc field-ownership table).
HUMAN_FRONTMATTER = ("scope", "confidence")  # status comes from directory; id is identity
MACHINE_FRONTMATTER = ("keywords", "created_at", "updated_at")  # never round-trip

def render_document(d: Decision, helpfulness: HelpfulnessScore | None) -> str:
    fm = {
        "id": d.id,
        "scope": d.scope,
        "confidence": d.confidence.value,
        "source_refs": [f"{r.ref}" for r in d.source_refs],
        # machine-owned (read-only): import ignores changes to these
        "keywords": list(d.keywords),
        "helpfulness_score": round(helpfulness.score, 2) if helpfulness else None,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }
    front = yaml.safe_dump(fm, sort_keys=False).strip()
    body = [
        "## Pattern", d.pattern, "",
        "## Rationale", d.rationale, "",
        "<!-- keywords / helpfulness_score / timestamps above are read-only:",
        "     machine-derived, regenerated by `metatron mirror sync` -->",
    ]
    return f"---\n{front}\n---\n\n" + "\n".join(body) + "\n"
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_mirror_render.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add metatron/mirror/render.py tests/test_mirror_render.py
git commit -m "feat(mirror): render a decision to a markdown document"
```

---

### Task 2: Render — parse a document back (human fields only)

**Files:**
- Modify: `metatron/mirror/render.py`
- Test: `tests/test_mirror_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mirror_render.py (append)
from metatron.mirror.render import parse_document

def test_parse_returns_human_fields_only():
    text = render_document(_decision(), helpfulness=None)
    parsed = parse_document(text)
    assert parsed["id"]                      # identity preserved
    assert parsed["scope"] == "web/api"
    assert parsed["confidence"] == "medium"
    assert parsed["pattern"] == "Use zod at API boundaries"
    assert parsed["rationale"].startswith("Hand-rolled")
    # machine-owned fields are NOT returned as editable
    assert "keywords" not in parsed
    assert "helpfulness_score" not in parsed
    assert "updated_at" not in parsed
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mirror_render.py::test_parse_returns_human_fields_only -q`
Expected: FAIL — `parse_document` not defined.

- [ ] **Step 3: Implement `parse_document`**

```python
# metatron/mirror/render.py (append)
def parse_document(text: str) -> dict:
    """Return ONLY human-owned fields from a mirror document.

    Machine-owned frontmatter is intentionally dropped so a hand-edit to it can
    never round-trip. Body sections map to pattern/rationale.
    """
    _, _, rest = text.partition("---\n")
    front_raw, _, body = rest.partition("\n---\n")
    fm = yaml.safe_load(front_raw) or {}
    out = {k: fm[k] for k in ("id", "scope", "confidence") if k in fm}
    if "source_refs" in fm:
        out["source_refs"] = fm["source_refs"]
    out["pattern"] = _section(body, "Pattern")
    out["rationale"] = _section(body, "Rationale")
    return out

def _section(body: str, heading: str) -> str:
    lines = body.splitlines()
    try:
        start = lines.index(f"## {heading}") + 1
    except ValueError:
        return ""
    collected = []
    for line in lines[start:]:
        if line.startswith("## ") or line.startswith("<!--"):
            break
        collected.append(line)
    return "\n".join(collected).strip()
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_mirror_render.py -q`
Expected: PASS (both render and parse tests).

- [ ] **Step 5: Round-trip property test**

```python
# tests/test_mirror_render.py (append)
def test_render_then_parse_preserves_human_fields():
    d = _decision()
    parsed = parse_document(render_document(d, helpfulness=None))
    assert parsed["id"] == d.id
    assert parsed["scope"] == d.scope
    assert parsed["pattern"] == d.pattern
    assert parsed["rationale"] == d.rationale
```

Run: `uv run pytest tests/test_mirror_render.py -q` → Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add metatron/mirror/render.py tests/test_mirror_render.py
git commit -m "feat(mirror): parse human-owned fields back from a document"
```

---

### Task 3: Layout — slug, path, and directory-as-status

**Files:**
- Create: `metatron/mirror/layout.py`
- Test: `tests/test_mirror_layout.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mirror_layout.py
from pathlib import Path
from metatron.models import Decision, Origin, Status
from metatron.mirror.layout import slug_for, path_for, status_for_path

def _d(status, pattern="Use zod at API boundaries"):
    return Decision(repo="r", pattern=pattern, scope="web/api", rationale="x",
                    origin=Origin.HUMAN, status=status)

def test_slug_is_stable_and_id_based():
    d = _d(Status.CANDIDATE)
    assert slug_for(d) == slug_for(d.model_copy(update={"pattern": "totally different"}))

def test_path_reflects_status_directory():
    assert path_for(_d(Status.CANDIDATE)).parent.name == "candidate"
    assert path_for(_d(Status.CANONICAL)).parent.name == "decisions"

def test_status_for_path_maps_directory():
    assert status_for_path(Path("metatron/candidate/x.md")) == Status.CANDIDATE
    assert status_for_path(Path("metatron/decisions/x.md")) == Status.CANONICAL
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mirror_layout.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `layout.py`**

```python
# metatron/mirror/layout.py
"""Stable file identity and directory-as-status mapping for the mirror.

Filename = readable slug + short hash of the durable decision id, so editing the
body never orphans git history and promotion is a clean `git mv`. The directory
(`candidate/` vs `decisions/`) *is* the status.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from metatron.models import Decision, Status

_STATUS_DIR = {Status.CANDIDATE: "candidate", Status.CANONICAL: "decisions"}
_DIR_STATUS = {v: k for k, v in _STATUS_DIR.items()}

def slug_for(d: Decision) -> str:
    head = re.sub(r"[^a-z0-9]+", "-", d.pattern.lower()).strip("-")[:50] or "decision"
    digest = hashlib.sha1(d.id.encode("utf-8")).hexdigest()[:6]
    return f"{head}-{digest}.md"

def path_for(d: Decision, root: Path = Path("metatron")) -> Path:
    return root / _STATUS_DIR[d.status] / slug_for(d)

def status_for_path(path: Path) -> Status:
    return _DIR_STATUS[Path(path).parent.name]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_mirror_layout.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add metatron/mirror/layout.py tests/test_mirror_layout.py
git commit -m "feat(mirror): slug, path, and directory-as-status layout"
```

---

### Task 4: Export — DB → bundle with sync markers

**Files:**
- Create: `metatron/mirror/export.py`
- Test: `tests/test_mirror_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mirror_export.py
import json
from pathlib import Path
from metatron.models import Decision, Origin, Status
from metatron.storage.sqlite import SQLiteDecisionStore, connect
from metatron.mirror.export import export_bundle

def _store(tmp_path):
    return SQLiteDecisionStore(connect(str(tmp_path / "d.db")))

def test_export_writes_one_file_per_decision_into_status_dirs(tmp_path):
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="cand pat", scope="a", rationale="x",
                       origin=Origin.AGENT_SUBMITTED, status=Status.CANDIDATE))
    store.add(Decision(repo="r", pattern="canon pat", scope="b", rationale="y",
                       origin=Origin.HUMAN, status=Status.CANONICAL))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    assert len(list((root / "metatron" / "candidate").glob("*.md"))) == 1
    assert len(list((root / "metatron" / "decisions").glob("*.md"))) == 1

def test_export_writes_sync_state_hashes(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    state = json.loads((root / "metatron" / ".sync-state.json").read_text())
    assert d.id in state

def test_export_is_idempotent(tmp_path):
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    first = {p: p.read_text() for p in (root / "metatron").rglob("*.md")}
    export_bundle(store, repo="r", root=root, events=[])
    second = {p: p.read_text() for p in (root / "metatron").rglob("*.md")}
    assert first == second
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mirror_export.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `export_bundle`**

```python
# metatron/mirror/export.py
"""DB → git-tracked bundle. Deterministic: re-running with no DB change is a no-op.

Rejected decisions are NOT mirrored (so rejected content can't be re-promoted by
moving a file). Writes a `.sync-state.json` of per-id content hashes for the
importer's collision detection.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from metatron.models import Status
from metatron.feedback_score import helpfulness_scores
from metatron.mirror.render import render_document
from metatron.mirror.layout import path_for

def export_bundle(store, repo: str, root: Path, events: list) -> dict[str, str]:
    scores = helpfulness_scores(events)
    state: dict[str, str] = {}
    for status in (Status.CANDIDATE, Status.CANONICAL):
        for d in store.list(repo=repo, status=status):
            text = render_document(d, helpfulness=scores.get(d.id))
            dest = root / path_for(d)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
            state[d.id] = hashlib.sha1(text.encode("utf-8")).hexdigest()
    state_path = root / "metatron" / ".sync-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    return state
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_mirror_export.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add metatron/mirror/export.py tests/test_mirror_export.py
git commit -m "feat(mirror): export decisions to a deterministic bundle"
```

---

### Task 5: Import — bundle → DB (status, human fields, machine guard, collisions)

**Files:**
- Create: `metatron/mirror/sync_import.py`
- Test: `tests/test_mirror_import.py`

- [ ] **Step 1: Write the failing test (promotion via directory)**

```python
# tests/test_mirror_import.py
import shutil
from pathlib import Path
from metatron.models import Decision, Origin, Status, Confidence
from metatron.storage.sqlite import SQLiteDecisionStore, connect
from metatron.mirror.export import export_bundle
from metatron.mirror.sync_import import import_bundle

def _store(tmp_path):
    return SQLiteDecisionStore(connect(str(tmp_path / "d.db")))

def test_moving_file_to_decisions_promotes_to_canonical(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.AGENT_SUBMITTED, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    src = next((root / "metatron" / "candidate").glob("*.md"))
    dst = root / "metatron" / "decisions" / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    result = import_bundle(store, repo="r", root=root)
    assert store.get(d.id).status == Status.CANONICAL
    assert d.id in result.promoted
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mirror_import.py::test_moving_file_to_decisions_promotes_to_canonical -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `import_bundle` (minimal: status + human fields)**

```python
# metatron/mirror/sync_import.py
"""Bundle → DB. Directory sets status; only human-owned fields apply; machine
fields are ignored (warned); concurrent DB+file edits are surfaced, not clobbered.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from metatron.models import Status, Confidence
from metatron.mirror.render import parse_document
from metatron.mirror.layout import status_for_path

@dataclass
class ImportResult:
    updated: list[str] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

def import_bundle(store, repo: str, root: Path) -> ImportResult:
    res = ImportResult()
    mirror = root / "metatron"
    for path in sorted(mirror.rglob("*.md")):
        text = path.read_text()
        fields = parse_document(text)
        did = fields.get("id")
        decision = store.get(did) if did else None
        if decision is None:
            continue  # new-file authoring handled in Task 6
        target = status_for_path(path)
        if decision.status != target:
            store.set_status(did, target)
            res.promoted.append(did)
        updates = {}
        if fields.get("pattern") and fields["pattern"] != decision.pattern:
            updates["pattern"] = fields["pattern"]
        if fields.get("rationale") and fields["rationale"] != decision.rationale:
            updates["rationale"] = fields["rationale"]
        if fields.get("scope") and fields["scope"] != decision.scope:
            updates["scope"] = fields["scope"]
        if fields.get("confidence"):
            updates["confidence"] = Confidence(fields["confidence"])
        if updates:
            store.update_fields(did, **updates)
            res.updated.append(did)
    return res
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_mirror_import.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing test (machine-field guard)**

```python
# tests/test_mirror_import.py (append)
def test_editing_keywords_in_file_is_ignored_and_warns(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE,
                           keywords=["orig"]))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("- orig", "- hacked"))
    res = import_bundle(store, repo="r", root=root)
    assert store.get(d.id).keywords == ["orig"]      # unchanged
    assert any("read-only" in w or "keywords" in w for w in res.warnings)
```

Implement the guard: in `import_bundle`, detect any change to machine frontmatter (re-parse raw YAML, compare `keywords`/timestamps to the decision) and append a warning to `res.warnings` without applying. (`parse_document` already excludes them from `updates`, so this is warning-only.)

Run: `uv run pytest tests/test_mirror_import.py -q` → Expected: PASS.

- [ ] **Step 6: Write the failing test (collision surfaced, not clobbered)**

```python
# tests/test_mirror_import.py (append)
def test_concurrent_db_and_file_edit_is_a_conflict(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="orig", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])     # records baseline hash
    # DB changes the same human field after the last sync...
    store.update_fields(d.id, pattern="db-changed")
    # ...and the file is edited too
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("orig", "file-changed"))
    res = import_bundle(store, repo="r", root=root)
    assert d.id in res.conflicts
    assert store.get(d.id).pattern == "db-changed"           # not clobbered
```

Implement collision detection: load `.sync-state.json`; recompute a hash of the decision's exported form *as it is now in the DB*; if it differs from the recorded baseline AND the file content also differs from baseline, record a conflict and skip applying that file. (Compare the DB-side render hash to `state[id]`; compare current file hash to `state[id]`.)

Run: `uv run pytest tests/test_mirror_import.py -q` → Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add metatron/mirror/sync_import.py tests/test_mirror_import.py
git commit -m "feat(mirror): import edits with status, field guard, and collision detection"
```

---

### Task 6: Import — author a brand-new decision from a hand-written file

**Files:**
- Modify: `metatron/mirror/sync_import.py`
- Test: `tests/test_mirror_import.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mirror_import.py (append)
def test_new_file_without_id_creates_a_decision(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "mirror"
    d_dir = root / "metatron" / "decisions"
    d_dir.mkdir(parents=True)
    (d_dir / "hand-authored.md").write_text(
        "---\nscope: web\nconfidence: high\n---\n\n"
        "## Pattern\nAlways gzip API responses.\n\n## Rationale\nBandwidth.\n")
    res = import_bundle(store, repo="r", root=root)
    created = store.list(repo="r", status=Status.CANONICAL)
    assert len(created) == 1
    assert created[0].pattern == "Always gzip API responses."
    assert created[0].origin == Origin.HUMAN
    assert created[0].id in res.updated
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mirror_import.py::test_new_file_without_id_creates_a_decision -q`
Expected: FAIL — id-less files are currently skipped.

- [ ] **Step 3: Implement new-file creation**

In `import_bundle`, when `did` is missing/unknown, build a `Decision(repo=repo, origin=Origin.HUMAN, status=status_for_path(path), pattern=..., rationale=..., scope=..., confidence=...)`, `store.add` it, and (optionally) rewrite the file with the assigned id so the next sync is stable. Append the new id to `res.updated`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_mirror_import.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add metatron/mirror/sync_import.py tests/test_mirror_import.py
git commit -m "feat(mirror): author new decisions from hand-written files"
```

---

### Task 7: OKF bundle export

**Files:**
- Create: `metatron/mirror/okf.py`
- Test: `tests/test_mirror_okf.py`

- [ ] **Step 1: Pin the OKF v0.1 manifest requirements**

Read the OKF v0.1 spec (GitHub, published 2026-06-12): note the required bundle manifest filename, fields, and document layout. Record the concrete requirements as a docstring in `okf.py`. (This resolves the design doc's open question on validation strictness.)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_mirror_okf.py
from pathlib import Path
from metatron.models import Decision, Origin, Status
from metatron.storage.sqlite import SQLiteDecisionStore, connect
from metatron.mirror.okf import export_okf_bundle, validate_okf_bundle

def test_okf_bundle_has_manifest_and_validates(tmp_path):
    store = SQLiteDecisionStore(connect(str(tmp_path / "d.db")))
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANONICAL))
    root = tmp_path / "okf"
    export_okf_bundle(store, repo="r", root=root, events=[])
    assert validate_okf_bundle(root) == []     # no structural errors
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_mirror_okf.py -q`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement `export_okf_bundle` + `validate_okf_bundle`**

Reuse `export_bundle`'s rendered documents; add the OKF manifest (per Step 1) at the bundle root and map decision fields into OKF's frontmatter envelope. `validate_okf_bundle` returns a list of structural error strings (empty = valid).

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_mirror_okf.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add metatron/mirror/okf.py tests/test_mirror_okf.py
git commit -m "feat(mirror): emit and validate an OKF v0.1 bundle"
```

---

### Task 8: CLI — `metatron mirror` subcommand group

**Files:**
- Modify: `metatron/cli.py` (subparser block near the `candidates`/`export` parsers ~line 733; dispatch in `main` ~line 220; add `_cmd_mirror`)
- Test: `tests/test_cli_mirror.py`

- [ ] **Step 1: Write the failing e2e test**

```python
# tests/test_cli_mirror.py
import io
from pathlib import Path
from metatron.cli import main

def test_mirror_sync_then_import_roundtrip(tmp_path, monkeypatch):
    db = tmp_path / "repo.db"
    # seed one decision via the store directly
    from metatron.storage.sqlite import SQLiteDecisionStore, connect
    from metatron.models import Decision, Origin, Status
    SQLiteDecisionStore(connect(str(db))).add(
        Decision(repo="r", pattern="p", scope="a", rationale="x",
                 origin=Origin.HUMAN, status=Status.CANDIDATE))
    out = io.StringIO()
    rc = main(["--db", str(db), "mirror", "sync", "--repo", "r",
               "--root", str(tmp_path / "m")], out=out)
    assert rc == 0
    assert list((tmp_path / "m" / "metatron" / "candidate").glob("*.md"))
    rc = main(["--db", str(db), "mirror", "import", "--repo", "r",
               "--root", str(tmp_path / "m")], out=out)
    assert rc == 0
```

(Match `main`'s actual signature for `out`/streams — check how `test_cli.py` invokes `main`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli_mirror.py -q`
Expected: FAIL — `invalid choice: 'mirror'`.

- [ ] **Step 3: Add the subparser group**

In `_build_parser`, after the `candidates` group:

```python
mirror_p = sub.add_parser("mirror", help="sync decisions to/from a git-tracked markdown bundle")
mirror_sub = mirror_p.add_subparsers(dest="mirror_command")
m_sync = mirror_sub.add_parser("sync", help="write decisions to the bundle (DB → files)")
m_sync.add_argument("--repo", default=None)
m_sync.add_argument("--root", default=".", help="repo root that holds metatron/")
m_sync.add_argument("--okf", action="store_true", help="also emit an OKF bundle")
m_import = mirror_sub.add_parser("import", help="apply edited bundle files (files → DB)")
m_import.add_argument("--repo", default=None)
m_import.add_argument("--root", default=".")
```

- [ ] **Step 4: Add dispatch + `_cmd_mirror`**

In `main`, alongside the other command branches:

```python
if args.command == "mirror":
    return _cmd_mirror(args, store, event_store, settings, out)
```

```python
def _cmd_mirror(args, store, event_store, settings, out) -> int:
    repo = _resolve_and_announce(args.repo, store, settings, out)
    root = Path(args.root)
    if args.mirror_command == "sync":
        from metatron.mirror.export import export_bundle
        export_bundle(store, repo=repo, root=root, events=event_store.list_events(repo=repo))
        if getattr(args, "okf", False):
            from metatron.mirror.okf import export_okf_bundle
            export_okf_bundle(store, repo=repo, root=root, events=event_store.list_events(repo=repo))
        print("Mirror synced.", file=out)
        return 0
    if args.mirror_command == "import":
        from metatron.mirror.sync_import import import_bundle
        res = import_bundle(store, repo=repo, root=root)
        for w in res.warnings:
            print(f"warning: {w}", file=out)
        for c in res.conflicts:
            print(f"conflict (skipped): {c}", file=out)
        print(f"Imported: {len(res.updated)} updated, {len(res.promoted)} promoted, "
              f"{len(res.conflicts)} conflicts.", file=out)
        return 0
    return 1
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_cli_mirror.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite + commit**

Run: `uv run pytest -q`
Expected: PASS (no regressions, especially `test_cli.py`, `test_cli_export.py`, `test_import.py`).

```bash
git add metatron/cli.py tests/test_cli_mirror.py
git commit -m "feat(cli): add the mirror subcommand group"
```

---

### Task 9: Docs + public OKF surface

**Files:**
- Modify: `README.md` (public), `docs/future-features.md` (move/close the relevant item if present)
- Test: `tests/test_readme.py` (verify it still passes; extend if it asserts command coverage)

- [ ] **Step 1: Document the feature in README**

Add a concise, neutral section: the `metatron/candidate/` + `metatron/decisions/` bundle, `metatron mirror sync` / `import`, directory-as-status, and first-class OKF export (`mirror sync --okf`). Keep copy product-focused; no references to this conversation.

- [ ] **Step 2: Run README test**

Run: `uv run pytest tests/test_readme.py -q`
Expected: PASS (adjust the section if the test enforces a command list).

- [ ] **Step 3: Commit**

```bash
git add README.md docs/future-features.md
git commit -m "docs: document the git-backed mirror and OKF export"
```

> Website copy (www-metatron) and a getmetatron.com/blog product post are a
> separate, follow-on change in those repos — out of scope for this plan, but
> the README section is the source copy they can draw from. Keep all of it neutral.

---

## Out of scope (deferred — see design doc)

- Auto-sync watcher / MCP auto-export on write.
- Mirroring and audit of `rejected` decisions.
- Three-way auto-merge instead of explicit collision surfacing.

## Final verification

- [ ] `uv run pytest -q` — full suite green.
- [ ] Manual smoke: in a scratch repo, `metatron mirror sync --okf`, edit a file, `git mv` a candidate into `decisions/`, `metatron mirror import`, confirm status flips and machine fields are untouched. Follow @superpowers:verification-before-completion before claiming done.
