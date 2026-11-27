"""A template's entity_type must be an entity type the app knows (400 otherwise).

Regression: the column is free text, so a misspelled type (``data-product``) could be
created and activated and then never applied to anything.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.controller.compliance_templates_manager import (
    ComplianceTemplatesManager,
    ComplianceUnknownEntityTypeError,
    _assert_known_entity_type,
)
from src.models.compliance_templates import ComplianceTemplateCreate, ComplianceTemplateRead
from src.models.process_workflows import EntityType
from src.repositories.compliance_templates_repository import compliance_templates_repo

UNKNOWN = ["data-product", "Data_Product", "product", "data_product ", "dataset_v2"]


@pytest.mark.parametrize("entity_type", [t.value for t in EntityType])
def test_every_known_entity_type_is_accepted(entity_type):
    _assert_known_entity_type(entity_type)


@pytest.mark.parametrize("entity_type", UNKNOWN)
def test_an_unknown_entity_type_is_refused(entity_type):
    with pytest.raises(ComplianceUnknownEntityTypeError):
        _assert_known_entity_type(entity_type)


@pytest.mark.parametrize("entity_type", UNKNOWN)
def test_create_refuses_an_unknown_entity_type_before_writing(entity_type):
    payload = ComplianceTemplateCreate(name="Governance", entity_type=entity_type, fields=[])
    db = MagicMock()
    with patch.object(compliance_templates_repo, "create_template") as create:
        with pytest.raises(ComplianceUnknownEntityTypeError):
            ComplianceTemplatesManager().create_template(db, payload=payload, user_email=None)
    create.assert_not_called()
    db.commit.assert_not_called()


def test_activate_refuses_a_stored_template_of_an_unknown_type():
    """A template created before this check still can't be switched on."""
    template = MagicMock(entity_type="data-product")
    db = MagicMock()
    with patch.object(compliance_templates_repo, "get_template", return_value=template), \
         patch.object(compliance_templates_repo, "activate_template") as activate:
        with pytest.raises(ComplianceUnknownEntityTypeError):
            ComplianceTemplatesManager().set_active(db, template_id=uuid4(), active=True)
    activate.assert_not_called()


def test_deactivate_of_such_a_template_is_still_allowed():
    template = MagicMock(entity_type="data-product")
    db = MagicMock()
    with patch.object(compliance_templates_repo, "get_template", return_value=template), \
         patch.object(compliance_templates_repo, "deactivate_template") as deactivate, \
         patch.object(ComplianceTemplateRead, "model_validate"):
        ComplianceTemplatesManager().set_active(db, template_id=uuid4(), active=False)
    deactivate.assert_called_once()
