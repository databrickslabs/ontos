"""init_db logs the database URL without the password."""
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.common import database

PASSWORD = 's3cr3t-Pa55'


def _password_settings():
    return SimpleNamespace(
        ENV='LOCAL', DB_USE_PASSWORD_AUTH=False,
        PGHOST='db.example.com', PGPORT=5432, PGDATABASE='ontos', PGUSER='ontos_app',
        PGPASSWORD=PASSWORD, PGSCHEMA='app_ontos',
        DB_ECHO=False, DB_POOL_SIZE=5, DB_MAX_OVERFLOW=10, DB_POOL_TIMEOUT=30, DB_POOL_RECYCLE=1800,
    )


def test_init_db_does_not_log_the_password(monkeypatch, caplog):
    # init_db resets these globals when it fails; monkeypatch puts them back afterwards.
    monkeypatch.setattr(database, '_engine', None)
    monkeypatch.setattr(database, '_SessionLocal', database._SessionLocal)
    monkeypatch.setattr(database, 'engine', database.engine)
    caplog.set_level(logging.DEBUG, logger=database.logger.name)
    with patch.object(database, 'get_settings', return_value=_password_settings()), \
            patch.object(database, 'ensure_database_and_schema_exist'), \
            patch.object(database, 'create_engine',
                         side_effect=RuntimeError('stop here')) as engine:
        with pytest.raises(ConnectionError):
            database.init_db()

    # The engine still gets the full URL; only the log is redacted.
    assert PASSWORD in engine.call_args.args[0]
    assert PASSWORD not in caplog.text
    redacted = 'postgresql+psycopg2://ontos_app:***@db.example.com:5432/ontos'
    assert f'> Database URL: {redacted}' in caplog.text
