"""Git-backed markdown mirror of decisions, and OKF bundle export.

SQLite stays authoritative; this package renders decisions to a git-tracked
bundle (export), parses human edits back applying only human-owned fields
(import), and lays the same files out as an Open Knowledge Format bundle.
"""
