"""Review follow-ups for "Create New Version", which now clones the contract (`POST /clone`).

- A new version made by the clone wasn't added to the search index (the old
  `create_new_version` path was), so it only showed up after a full reindex.
- Committing a personal draft didn't add the now team-visible version to the
  index either.
- The clone requires `X.Y.Z`; a version in another form answered a generic
  400 "Invalid contract data". It now answers `invalid_version_format` with
  the version, so the page can say it in the user's language.
"""
import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.common.api_errors import coded_http_exception_handler
from src.controller.data_contracts_manager import DataContractsManager, InvalidVersionFormatError

SERVERS = [
    {'id': 'srv-named', 'server': 'prod-db', 'type': 'postgres', 'host': 'db.example.com'},
    # ODCS requires `server`, but imports accept a server without it
    {'id': 'srv-unnamed', 'type': 'databricks', 'catalog': 'main'},
]


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


@pytest.fixture
def imported(db_session: Session):
    manager = _manager()
    doc = {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': f'orders-{uuid.uuid4().hex[:6]}', 'version': '1.0.0', 'status': 'draft',
        'servers': [dict(s) for s in SERVERS],
    }
    contract = manager.create_from_upload(db_session, doc, current_user='alice')
    db_session.commit()
    return manager, contract.id


# --- search index ---------------------------------------------------------

def test_a_new_version_is_added_to_the_search_index(db_session, imported):
    manager, cid = imported
    manager._notify_index_upsert = MagicMock()

    new = manager.clone_contract_for_new_version(db_session, cid, '2.0.0', current_user='alice')

    indexed = [call.args[0].id for call in manager._notify_index_upsert.call_args_list]
    assert any(new.id in item_id for item_id in indexed)


def test_a_personal_draft_is_not_added_to_the_search_index(db_session, imported):
    manager, cid = imported
    manager._notify_index_upsert = MagicMock()

    manager.clone_contract_for_new_version(
        db_session, cid, '1.0.0-draft', current_user='alice', as_personal_draft=True,
    )

    manager._notify_index_upsert.assert_not_called()


def test_a_committed_personal_draft_is_added_to_the_search_index(db_session, imported):
    manager, cid = imported
    manager._notify_index_upsert = MagicMock()
    draft = manager.clone_contract_for_new_version(
        db_session, cid, '1.0.0-draft', current_user='alice', as_personal_draft=True,
    )
    manager._notify_index_upsert.assert_not_called()

    committed = manager.commit_personal_draft(
        db_session, draft.id, '1.1.0', 'Ready for the team', current_user='alice',
    )

    assert committed.draft_owner_id is None
    indexed = [call.args[0].id for call in manager._notify_index_upsert.call_args_list]
    assert any(committed.id in item_id for item_id in indexed)


# --- version format -------------------------------------------------------

@pytest.mark.parametrize('version', ['2.1', 'v2.0.0', '2.0.0-rc1'])
def test_a_version_not_in_x_y_z_form_is_refused_with_its_code(db_session, imported, version):
    manager, cid = imported

    with pytest.raises(InvalidVersionFormatError) as refused:
        manager.clone_contract_for_new_version(db_session, cid, version, current_user='alice')

    assert refused.value.code == 'invalid_version_format'
    assert refused.value.params == {'version': version}
    # The English message is unchanged
    assert str(refused.value) == 'new_version must be in format X.Y.Z (e.g., 2.0.0)'


def test_the_clone_route_answers_the_code_and_the_version(db_session, imported):
    from src.routes.data_contracts_routes import clone_contract_for_new_version
    manager, cid = imported
    request = SimpleNamespace(client=None)
    user = SimpleNamespace(username='alice')

    with pytest.raises(HTTPException) as raised:
        asyncio.run(clone_contract_for_new_version(
            cid, request, db_session, MagicMock(), user, body={'new_version': '2.1'}, manager=manager,
        ))

    response = asyncio.run(coded_http_exception_handler(MagicMock(), raised.value))
    assert response.status_code == 400
    assert json.loads(response.body)['detail'] == {
        'code': 'invalid_version_format',
        'message': 'new_version must be in format X.Y.Z (e.g., 2.0.0)',
        'params': {'version': '2.1'},
    }
