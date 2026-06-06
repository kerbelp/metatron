"""Concurrency behaviour of the SQLite stores.

In production several processes open the *same* per-repo file at once: every
running ``metatron serve`` plus ``metatron ui`` and CLI commands. Reads
(``get_decisions_for_context``) and writes (``submit_feedback`` /
``submit_candidate_decision``) interleave constantly. Under SQLite's default
rollback journal an open read holds a SHARED lock that blocks a writer's commit,
surfacing as ``database is locked`` / ``attempt to write a readonly database``.
WAL mode plus a busy timeout lets readers and writers proceed concurrently.
"""

import sqlite3

from metatron.events import Event, EventKind
from metatron.storage.sqlite import SQLiteEventStore


def _event() -> Event:
    return Event(repo="github.com/acme/app", kind=EventKind.SUBMIT, area="src/x")


def test_open_reader_does_not_block_a_writer(tmp_path):
    db = tmp_path / "concur.db"
    reader = SQLiteEventStore(str(db))
    writer = SQLiteEventStore(str(db))

    # A reader holds an open (uncommitted) read transaction — a SHARED lock that
    # never releases for the duration of this write, mirroring overlapping live
    # connections from other serve processes.
    reader._conn.execute("BEGIN")
    reader._conn.execute("SELECT * FROM events").fetchall()

    # The writer must still be able to record. Under the default journal this
    # blocks on the reader's SHARED lock and eventually raises; WAL lets it
    # through immediately.
    writer.record(_event())  # must not raise

    reader._conn.rollback()
    reader.close()
    writer.close()
