"""Repository Verification Layer (RVL).

Git-tracked, human-reviewed verification contracts served beside decisions:
*how to prove a change works, and what a failure implies.* This package parses
contracts, discovers/selects them by scope, evaluates them (operator/CI only —
never over the serving path), and scaffolds new ones.

See ``docs/designs/2026-07-21-repository-verification-layer.md``.
"""
