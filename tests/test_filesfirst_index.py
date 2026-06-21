from pathlib import Path
from metatron.filesfirst.index import build_index, write_index


def _write(d, name, body):
    (d / name).write_text(body, encoding="utf-8")


def test_index_has_a_row_per_decision(tmp_path):
    _write(tmp_path, "token-refresh-strategy.md",
           "---\nid: token-refresh-strategy\ntype: decision\nstatus: canonical\n"
           "title: Refresh server-side\nkeywords: [auth, tokens]\n---\nb\n")
    out = build_index(tmp_path)
    assert "token-refresh-strategy" in out
    assert "canonical" in out
    assert "auth, tokens" in out
    assert out.startswith("# Decision index")


def test_index_skips_reserved_files(tmp_path):
    _write(tmp_path, "index.md", "stale\n")
    _write(tmp_path, "a.md",
           "---\nid: a\ntype: decision\nstatus: candidate\ntitle: A\n---\nb\n")
    out = build_index(tmp_path)
    assert "stale" not in out
    assert "| `a` |" in out


def test_index_coerces_scalar_keywords(tmp_path):
    # A scalar `keywords: auth` must render as `auth`, not char-by-char `a, u, t, h`.
    _write(tmp_path, "a.md",
           "---\nid: a\ntype: decision\nstatus: candidate\ntitle: A\nkeywords: auth\n---\nb\n")
    out = build_index(tmp_path)
    assert "| auth |" in out
    assert "a, u, t, h" not in out


def test_write_index_creates_file(tmp_path):
    _write(tmp_path, "a.md",
           "---\nid: a\ntype: decision\nstatus: candidate\ntitle: A\n---\nb\n")
    path = write_index(tmp_path)
    assert path == tmp_path / "index.md"
    assert "| `a` |" in path.read_text(encoding="utf-8")
