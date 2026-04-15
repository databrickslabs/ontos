"""SemanticModelsManager.update: display_name and forbidden name changes."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.controller.semantic_models_manager import SemanticModelsManager
from src.db_models.semantic_models import SemanticModelDb
from src.models.semantic_models import SemanticModelUpdate
from src.repositories.semantic_models_repository import semantic_models_repo
import uuid


@pytest.fixture
def manager_no_rebuild(db_session):
    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", lambda self: None):
        yield SemanticModelsManager(db_session, data_dir=Path("/tmp/ontos-test-semantic"))


def test_update_display_name(manager_no_rebuild, db_session):
    mid = str(uuid.uuid4())
    db_obj = SemanticModelDb(
        id=mid,
        name="file.ttl",
        format="skos",
        content_text="@prefix : <http://ex/> . :a a :C .",
    )
    db_session.add(db_obj)
    db_session.commit()

    updated = manager_no_rebuild.update(mid, SemanticModelUpdate(display_name="  Nice Title  "), "tester")
    assert updated is not None
    assert updated.display_name == "Nice Title"

    row = semantic_models_repo.get(db_session, id=mid)
    assert row.display_name == "Nice Title"


def test_update_clear_display_name(manager_no_rebuild, db_session):
    mid = str(uuid.uuid4())
    db_obj = SemanticModelDb(
        id=mid,
        name="x.ttl",
        format="skos",
        content_text="@prefix : <http://ex/> . :a a :C .",
        display_name="Was Set",
    )
    db_session.add(db_obj)
    db_session.commit()

    updated = manager_no_rebuild.update(mid, SemanticModelUpdate(display_name=""), "tester")
    assert updated.display_name is None


def test_update_name_change_forbidden(manager_no_rebuild, db_session):
    mid = str(uuid.uuid4())
    db_obj = SemanticModelDb(
        id=mid,
        name="stable.ttl",
        format="skos",
        content_text="@prefix : <http://ex/> . :a a :C .",
    )
    db_session.add(db_obj)
    db_session.commit()

    with pytest.raises(ValueError, match="Renaming semantic models"):
        manager_no_rebuild.update(mid, SemanticModelUpdate(name="other.ttl"), "tester")
