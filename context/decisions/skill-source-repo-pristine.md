---
type: Metatron Decision
scope: .roo/skills
confidence: high
---

## Pattern
The `.roo/skills/` copies in this repository must stay byte-identical to the
packaged sources in `metatron/okf_skills/`. Tooling that adapts installed
skill copies (path substitution, review-gate notes) must detect the skill
source repo and leave its copies pristine; `context setup` does this via
`_is_skill_source_repo`.

## Rationale
This repo is where the packaged skills are developed: the parity test
(`test_packaged_skills_match_repo_skills`) guards against drift between what
ships in the wheel and what the repo itself uses. Gate-adapted copies are
correct in consumer repos but break parity — and CI — here.
