"""Real competing connections prove writers are released at operation boundaries."""
import sqlite3
import pytest


def writer_available(path):
    with sqlite3.connect(path, timeout=0) as other:
        other.execute('BEGIN IMMEDIATE')
        other.rollback()


def test_metadata_read_releases_its_cache_write(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom, 'INDEX_READ_ONLY', False)
    path = tmp_path / 'index.sqlite'
    conn = navcom.open_index(path)
    navcom.session_meta(conn, '/missing/session.jsonl', 'codex')
    assert not conn.in_transaction
    writer_available(path)
    conn.close()


def test_index_releases_between_files_and_after_failure(navcom, tmp_path, monkeypatch):
    path = tmp_path / 'index.sqlite'
    conn = navcom.open_index(path)
    calls = []
    def index_one(conn, log, force=False):
        writer_available(path)
        conn.execute('INSERT INTO file_meta VALUES (?, ?, ?, ?)', (log[0], 'codex', '', 'title'))
        calls.append(log[0])
        if log[0] == 'bad': raise RuntimeError('parser failed')
        return True
    monkeypatch.setattr(navcom, 'index_log', index_one)
    with pytest.raises(RuntimeError):
        navcom._index_logs(conn, [('ok',1,1,'codex'),('bad',1,1,'codex')], upgrade=False)
    assert calls == ['ok', 'bad']
    assert not conn.in_transaction
    writer_available(path)
    assert conn.execute('SELECT file FROM file_meta').fetchall() == [('ok',)]
    conn.close()


def test_failed_schema_initialization_closes_connection(navcom, tmp_path, monkeypatch):
    connections = []
    def broken(conn):
        connections.append(conn)
        conn.execute('CREATE TABLE example (n INTEGER)')
        conn.execute('INSERT INTO example VALUES (1)')
        raise sqlite3.OperationalError('migration failure')
    monkeypatch.setattr(navcom, '_initialize_index', broken)
    with pytest.raises(sqlite3.OperationalError):
        navcom._open_index_rw(tmp_path / 'index.sqlite')
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute('SELECT 1')


def test_transient_lock_does_not_disable_future_indexing(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom, 'INDEX_READ_ONLY', False)
    path = tmp_path / 'index.sqlite'
    conn = navcom.open_index(path)
    conn.execute('PRAGMA busy_timeout=0')
    blocker = sqlite3.connect(path)
    blocker.execute('BEGIN IMMEDIATE')
    def write(conn, *args):
        conn.execute("INSERT INTO file_meta VALUES ('k', 'codex', '', '')")
        conn.commit()
        return 1
    monkeypatch.setattr(navcom, '_index_logs', write)
    try:
        assert navcom.index_logs(conn, []) == 0
        assert not navcom.INDEX_READ_ONLY
        navcom.session_meta(conn, '/missing/session.jsonl', 'codex')
        assert not conn.in_transaction
    finally:
        blocker.rollback(); blocker.close()
    assert navcom.index_logs(conn, []) == 1
    writer_available(path)
    conn.close()
