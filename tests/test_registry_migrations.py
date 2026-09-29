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
