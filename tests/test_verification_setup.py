from metatron.verification.setup import EXAMPLE_SLUG, run_verification_setup
from metatron.verification.contract import load_contract
from metatron.verification.runner import run_contracts


def test_setup_writes_block_and_runnable_example(tmp_path):
    run_verification_setup(tmp_path)
    agents = tmp_path / "AGENTS.md"
    assert agents.exists()
    body = agents.read_text()
    assert "METATRON:VERIFICATION:START" in body
    assert "verification run" in body

    example = tmp_path / "context" / "verification" / f"{EXAMPLE_SLUG}.md"
    assert example.exists()
    # the bundled example actually runs green out of the box
    report = run_contracts([load_contract(example)], cwd=tmp_path)
    assert report.passed


def test_setup_is_idempotent(tmp_path):
    run_verification_setup(tmp_path)
    first = (tmp_path / "AGENTS.md").read_text()
    res = run_verification_setup(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text() == first  # block not duplicated
    assert any("already" in m for m in res.messages)


def test_setup_preserves_existing_agents_content(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# My rules\n\nkeep me\n", encoding="utf-8")
    run_verification_setup(tmp_path)
    body = (tmp_path / "AGENTS.md").read_text()
    assert "keep me" in body
    assert "METATRON:VERIFICATION:START" in body


def test_setup_candidates_gate_targets_candidate_dir(tmp_path):
    run_verification_setup(tmp_path, review_gate="candidates")
    assert (tmp_path / "context" / "candidate" / f"{EXAMPLE_SLUG}.md").exists()
    assert not (tmp_path / "context" / "verification" / f"{EXAMPLE_SLUG}.md").exists()
