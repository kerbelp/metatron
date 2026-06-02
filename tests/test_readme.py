"""Guard: the README's command reference must stay in sync with the CLI.

A docs PR can't have much to test, but this one cheap invariant catches the most
likely drift — a new subcommand added to the CLI but never documented.
"""

from argparse import _SubParsersAction
from pathlib import Path

from metatron.cli import _build_parser

README = (Path(__file__).parent.parent / "README.md").read_text()


def test_readme_documents_every_cli_subcommand():
    parser = _build_parser()
    sub = next(a for a in parser._actions if isinstance(a, _SubParsersAction))
    missing = [name for name in sub.choices if name not in README]
    assert not missing, f"README.md does not document CLI commands: {missing}"


def test_readme_documents_every_mcp_tool():
    for tool in (
        "get_priors_for_context",
        "submit_feedback",
        "submit_candidate_learning",
    ):
        assert tool in README, f"README.md does not document MCP tool {tool!r}"
