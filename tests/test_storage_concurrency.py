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
from metatron.storage.sqlite import SQLiteEventStore, connect


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


def test_connection_runs_in_autocommit(tmp_path):
    """Connections hold no implicit transaction across statements.

    Legacy isolation mode opens an implicit transaction before the first write and
    keeps it open until the next ``commit()``. Because ``metatron ui`` shares one
    connection between the request thread and its background job threads, such a
    lingering transaction pinned the connection to a single WAL snapshot and froze
    every later UI read (the "real-time doesn't update" bug). Autocommit prevents
    it: a write is durable and visible to other connections immediately.
    """
    db = tmp_path / "autocommit.db"
    conn = connect(str(db))
    assert conn.isolation_level is None  # autocommit

    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")  # no explicit commit
    assert conn.in_transaction is False  # nothing held open

    # A second connection (another process) sees the write right away.
    other = connect(str(db))
    assert other.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1

    conn.close()
    other.close()


def test_pending_write_does_not_freeze_a_long_lived_reader(tmp_path):
    """A connection used for writes must still see other processes' fresh commits.

    Mirrors the live bug directly: a background job issues a write on the shared
    connection, then a separate process (a running ``metatron serve``) records a
    new event. In legacy mode the job's uncommitted transaction held a write lock
    and a frozen snapshot, so the new event was both unwritable and unseen. In
    autocommit the write settled immediately, so the long-lived connection reads
    the new event in real time.
    """
    db = tmp_path / "live.db"
    server = SQLiteEventStore(str(db))
    server.record(_event())

    # A write on the shared connection, of the kind a background job performs.
    server._conn.execute("UPDATE events SET handled = handled")

    # Another process records a brand-new event.
    other = SQLiteEventStore(str(db))
    other.record(Event(repo="github.com/acme/app", kind=EventKind.QUERY, area="a"))
    other.close()

    kinds = [e.kind for e in server.list_events(repo="github.com/acme/app")]
    assert EventKind.QUERY in kinds  # seen live, not frozen at an old snapshot
    server.close()
