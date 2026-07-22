from __future__ import annotations

# A verification contract is an OKF concept with this declared type. It is a
# sibling status class to a decision — same frontmatter/scope/lifecycle machinery
# (see docs/designs/2026-07-21-repository-verification-layer.md).
OKF_TYPE = "Metatron Verification"

# The status directory contracts live in, beside decisions/ and candidate/.
VERIFICATION_DIR = "verification"

# Section headings the parser keys off. Order is the execution order for run().
SECTION_ASSUMPTIONS = "Assumptions"
SECTION_SETUP = "Setup"
SECTION_CHECKS = "Checks"
SECTION_FAILURE_MEANS = "Failure Means"
SECTION_JUDGED = "Judged invariants"
SECTION_TEARDOWN = "Teardown"

SECTIONS = (
    SECTION_ASSUMPTIONS,
    SECTION_SETUP,
    SECTION_CHECKS,
    SECTION_FAILURE_MEANS,
    SECTION_JUDGED,
    SECTION_TEARDOWN,
)

# Deterministic assertion kinds the runner evaluates against a check's captured
# exit code / stdout / stderr. `judge` is phase-2 (LLM-evaluated, opt-in) and is
# never run by the default executable path.
ASSERTION_KINDS = ("exit", "contains", "matches", "jsonpath", "shell")

# Reserved OKF filenames that are listings/history, never contracts.
RESERVED_FILENAMES = frozenset({"index.md", "log.md"})
