"""Local employee identity: read/seed/write the ~/.metatron/config.toml [identity]."""

from metatron import identity


def test_load_identity_absent_is_anonymous(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    ident = identity.load_identity()
    assert ident.actor_id == "" and ident.email == "" and ident.display_name == ""


def test_set_identity_persists_and_derives_actor_id(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    saved = identity.set_identity(email="kerbelp@gmail.com", display_name="Pavel Kerbel")
    assert saved.email == "kerbelp@gmail.com"
    assert saved.display_name == "Pavel Kerbel"
    assert saved.actor_id  # derived, stable
    # round-trips from disk
    again = identity.load_identity()
    assert again == saved
    assert identity.config_path().exists()


def test_actor_id_is_stable_for_an_email(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    a = identity.set_identity(email="a@x.com").actor_id
    b = identity.set_identity(email="a@x.com").actor_id
    assert a == b


def test_ensure_identity_seeds_from_git_when_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(identity, "_from_git",
                        lambda: identity.Identity(email="dev@corp.com",
                                                  display_name="Dev", actor_id="abc123"))
    ident = identity.ensure_identity()
    assert ident.email == "dev@corp.com"
    # persisted, so the next process doesn't re-run git
    assert identity.load_identity().email == "dev@corp.com"


def test_ensure_identity_stays_anonymous_when_no_git(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(identity, "_from_git", lambda: None)
    assert identity.ensure_identity().actor_id == ""


def test_whoami_cli_sets_then_shows(tmp_path, monkeypatch):
    import io

    from metatron.cli import main

    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    out = io.StringIO()
    assert main(["whoami", "--set-email", "kerbelp@gmail.com", "--set-name", "Pavel"],
                out=out) == 0
    out2 = io.StringIO()
    assert main(["whoami"], out=out2) == 0
    assert "Pavel" in out2.getvalue() and "kerbelp@gmail.com" in out2.getvalue()
