"""The repo catalog: one self-contained SQLite file per repo."""

import sqlite3

from metatron.storage.catalog import Catalog, slug_for


def test_slug_is_deterministic_readable_and_collision_safe():
    a = slug_for("github.com/acme/app")
    b = slug_for("gitlab.com/acme/app")
    assert a.endswith(".db") and a.startswith("app-")
    assert slug_for("github.com/acme/app") == a  # deterministic
    assert a != b  # same tail, different id -> different file


def test_open_creates_self_describing_file(tmp_path):
    cat = Catalog(str(tmp_path))
    stores = cat.open("github.com/acme/app")
    path = cat.path_for("github.com/acme/app")
    assert path.exists()
    row = sqlite3.connect(path).execute("SELECT repo_id FROM repo_meta").fetchone()
    assert row[0] == "github.com/acme/app"
    stores.priors.close()
    stores.events.close()
    stores.runs.close()


def test_single_file_mode_treats_one_file_as_the_world(tmp_path):
    # Create a repo file via a directory catalog, then re-open that file directly:
    # the recipient's hand-off path. It must report the lone repo regardless of name.
    dir_cat = Catalog(str(tmp_path / "data"))
    dir_cat.open("acme/app")
    file_path = dir_cat.path_for("acme/app")
    dir_cat.close()

    file_cat = Catalog(str(file_path))
    assert file_cat.list_repos() == ["acme/app"]
    assert file_cat.path_for("anything-else") == file_path
