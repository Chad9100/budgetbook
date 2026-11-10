import sqlite3

import flask
import pytest

from budgetbook import __version__
from budgetbook.cli import main
from budgetbook.db import DEFAULT_CATEGORIES, SCHEMA_VERSION


def test_init_creates_db_with_starter_categories(tmp_path, capsys):
    path = tmp_path / "data" / "money.db"
    assert main(["init", "--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Created database" in out and "starter categories" in out
    conn = sqlite3.connect(path)
    names = [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY id")]
    assert names == DEFAULT_CATEGORIES
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_init_is_idempotent_and_respects_no_categories(tmp_path, capsys):
    path = tmp_path / "a.db"
    assert main(["init", "--db", str(path), "--no-categories"]) == 0
    assert main(["init", "--db", str(path), "--no-categories"]) == 0
    assert "Database ready" in capsys.readouterr().out
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0
    conn.close()


def test_init_uses_env_var(tmp_path, monkeypatch):
    path = tmp_path / "env.db"
    monkeypatch.setenv("BUDGETBOOK_DB", str(path))
    assert main(["init"]) == 0
    assert path.exists()


def test_run_starts_flask_on_localhost(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(flask.Flask, "run", lambda self, **kw: calls.append((self, kw)))
    path = tmp_path / "run.db"
    assert main(["run", "--db", str(path), "--port", "5055"]) == 0
    app, kw = calls[0]
    assert kw == {"host": "127.0.0.1", "port": 5055, "debug": False}
    assert app.config["DATABASE"] == str(path)
    # a session key was generated and stored next to the database
    secret = (tmp_path / "run.db.secret").read_text()
    assert app.config["SECRET_KEY"] == secret and len(secret) == 64
    assert "warning" not in capsys.readouterr().err


def test_run_warns_when_exposed_and_reuses_secret(tmp_path, monkeypatch, capsys):
    keys = []
    monkeypatch.setattr(flask.Flask, "run", lambda self, **kw: keys.append(self.config["SECRET_KEY"]))
    path = str(tmp_path / "x.db")
    main(["run", "--db", path, "--host", "0.0.0.0"])
    main(["run", "--db", path])
    assert "warning: listening on 0.0.0.0" in capsys.readouterr().err
    assert keys[0] == keys[1]


def test_run_rejects_bad_port(tmp_path, capsys):
    assert main(["run", "--db", str(tmp_path / "x.db"), "--port", "70000"]) == 2
    assert "--port" in capsys.readouterr().err


def test_version_and_missing_command(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main([])


def _seed(path):
    main(["init", "--db", str(path)])
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO transactions (date, amount_cents, payee) VALUES ('2025-01-02', -500, 'Cafe')")
    conn.commit()
    conn.close()


def test_backup_copies_data(tmp_path, capsys):
    src, dest = tmp_path / "a.db", tmp_path / "out" / "b.db"
    _seed(src)
    assert main(["backup", "--db", str(src), "--out", str(dest)]) == 0
    assert "Backed up 1 transactions" in capsys.readouterr().out
    conn = sqlite3.connect(dest)
    assert conn.execute("SELECT payee FROM transactions").fetchone()[0] == "Cafe"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_backup_refuses_overwrite_unless_forced(tmp_path, capsys):
    src, dest = tmp_path / "a.db", tmp_path / "b.db"
    _seed(src)
    dest.write_text("keep me")
    assert main(["backup", "--db", str(src), "--out", str(dest)]) == 1
    assert dest.read_text() == "keep me"
    assert "already exists" in capsys.readouterr().err
    assert main(["backup", "--db", str(src), "--out", str(dest), "--force"]) == 0
    conn = sqlite3.connect(dest)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    conn.close()


def test_backup_missing_db_and_same_file(tmp_path, capsys):
    missing = tmp_path / "none.db"
    assert main(["backup", "--db", str(missing), "--out", str(tmp_path / "o.db")]) == 1
    assert "backup failed" in capsys.readouterr().err
    assert not missing.exists()
    _seed(tmp_path / "a.db")
    assert main(["backup", "--db", str(tmp_path / "a.db"), "--out", str(tmp_path / "a.db")]) == 2


def test_backup_default_name_in_cwd(tmp_path, monkeypatch):
    _seed(tmp_path / "a.db")
    monkeypatch.chdir(tmp_path)
    assert main(["backup", "--db", "a.db"]) == 0
    assert len(list(tmp_path.glob("budgetbook-backup-*.db"))) == 1
