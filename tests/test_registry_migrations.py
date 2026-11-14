from preview_hub import registry


def test_migrations_ignore_non_revision_sql(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_initial.sql").write_text("CREATE TABLE valid (id INTEGER);")
    for name in ("._0001_initial.sql", "README.sql", "1_short.sql", "00002_long.sql"):
        (migrations / name).write_text("INVALID SQL")
    monkeypatch.setattr(registry, "__file__", str(tmp_path / "registry.py"))
    store = registry.Registry(tmp_path / "state")
    store.migrate()
    with store.connect() as db:
        assert db.execute("SELECT value FROM schema_meta").fetchone()[0] == "1"
        assert db.execute("SELECT * FROM valid").fetchall() == []


def test_stage_migration_preserves_existing_database(tmp_path):
    import sqlite3
    from pathlib import Path

    db = sqlite3.connect(tmp_path / "state.db")
    db.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO schema_meta VALUES ('version', '3')")
    for file in sorted((Path(registry.__file__).parent / "migrations").glob("*.sql")):
        if file.name < "0004":
            db.executescript(file.read_text())
    db.execute("INSERT INTO bot_cursors VALUES ('org/repo', 'preserved', 'today')")
    db.commit()
    db.close()
    store = registry.Registry(tmp_path)
    with store.connect() as db:
        assert db.execute("SELECT value FROM schema_meta").fetchone()[0] == "4"
        assert (
            db.execute(
                "SELECT comments_since FROM bot_cursors WHERE repo='org/repo'"
            ).fetchone()[0]
            == "preserved"
        )
        assert db.execute("SELECT * FROM operation_stages").fetchall() == []
    store.migrate()
