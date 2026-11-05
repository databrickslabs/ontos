"""Connection configs: secret-like values are masked in responses and kept on masked updates."""

from src.controller.connections_manager import SECRET_MASK, ConnectionsManager, redact_config
from src.models.connections import ConnectionCreate, ConnectionUpdate


def test_redact_config_masks_secrets_but_not_references():
    config = {
        "client_secret": "abc",
        "password": "pw",
        "secret_scope": "tableau",
        "secret_key": "app-secret",
        "secret_id": "kid-1",
        "pat_name": "ontos",
        "server_url": "https://t",
        "token": "",
    }
    redacted = redact_config(config)
    assert redacted["client_secret"] == SECRET_MASK
    assert redacted["password"] == SECRET_MASK
    assert redacted["token"] == ""  # nothing to hide
    for key in ("secret_scope", "secret_key", "secret_id", "pat_name", "server_url"):
        assert redacted[key] == config[key]


def test_manager_masks_on_read_and_keeps_secret_on_masked_update(db_session):
    manager = ConnectionsManager(db_session)
    created = manager.create_connection(ConnectionCreate(
        name="pbi", connector_type="powerbi", config={"tenant_id": "t", "client_secret": "real"},
    ))
    assert created.config["client_secret"] == SECRET_MASK

    updated = manager.update_connection(created.id, ConnectionUpdate(config={"tenant_id": "t2", "client_secret": SECRET_MASK}))
    assert updated.config == {"tenant_id": "t2", "client_secret": SECRET_MASK}

    from src.repositories.connections_repository import connections_repo
    assert connections_repo.get(db_session, created.id).config["client_secret"] == "real"
