"""Tests for prompt loading and the output-language directive."""

from metatron.extraction.prompts import load_prompt, render


def test_english_default_leaves_prompt_unchanged():
    # The historical English-only behaviour: no directive is appended.
    assert load_prompt("extract_decisions", language="english") == load_prompt(
        "extract_decisions", language="ENGLISH"
    )
    assert "Output language:" not in load_prompt("extract_decisions", language="english")


def test_non_english_appends_directive():
    prompt = load_prompt("extract_decisions", language="french")

    assert "Output language:" in prompt
    assert "french" in prompt
    # The base template is still present in full.
    assert "Return ONLY a JSON array." in prompt


def test_directive_reaffirms_json_only_output_last():
    # The base templates end with a "no prose outside the JSON array" instruction.
    # Appending the language directive after it would leave a content instruction as
    # the final thing the model reads, so the directive must re-assert the output
    # format as its closing sentence.
    prompt = load_prompt("extract_decisions", language="french")

    tail = prompt.rstrip()
    assert tail.endswith("with no prose outside it.")
    assert "JSON array" in tail.rsplit("Output language:", 1)[1]


def test_directive_survives_render():
    # The appended directive carries no ``{placeholder}`` braces, so rendering the
    # template through ``str.format`` must not raise.
    prompt = load_prompt("extract_decisions", language="french")
    rendered = render(prompt, scope="storage", signals="imports: sqlite3")

    assert "Output language:" in rendered
    assert "storage" in rendered


def test_language_resolution_reads_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("METATRON_OUTPUT_LANGUAGE", raising=False)
    (tmp_path / "metatron.toml").write_text('[metatron]\noutput_language = "spanish"\n')

    # No explicit language: it is resolved from metatron.toml in the cwd.
    prompt = load_prompt("extract_decisions")

    assert "Output language:" in prompt
    assert "spanish" in prompt
