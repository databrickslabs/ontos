"""Indirect contract delivery serializes the contract before the request session closes."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import BackgroundTasks

from src.common.delivery_mixin import DeliveryMixin
from src.controller.delivery_service import (
    DeliveryChangeType,
    DeliveryMode,
)
from src.file_models.data_contracts import DataContractFileModel


class ContractDelivery(DeliveryMixin):
    DELIVERY_ENTITY_TYPE = "DataContract"


def test_indirect_mode_runs_before_background_modes(monkeypatch):
    delivery_service = MagicMock()
    delivery_service.get_active_modes.return_value = [
        DeliveryMode.INDIRECT,
        DeliveryMode.MANUAL,
    ]
    delivery_service.deliver.return_value.all_success = True
    monkeypatch.setattr(
        "src.controller.delivery_service.get_delivery_service",
        lambda: delivery_service,
    )
    background_tasks = BackgroundTasks()
    contract = SimpleNamespace(id="contract-1")

    queued = ContractDelivery()._queue_delivery(
        entity=contract,
        change_type=DeliveryChangeType.CONTRACT_CREATE,
        user="producer@example.com",
        background_tasks=background_tasks,
    )

    assert queued is True
    delivery_service.deliver.assert_called_once()
    assert delivery_service.deliver.call_args.kwargs["modes"] == [DeliveryMode.INDIRECT]
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].args[1] == [DeliveryMode.MANUAL]


def test_contract_file_model_uses_current_odcs_orm_fields():
    contract = SimpleNamespace(
        id="contract-1",
        name="Marketplace Order Events",
        base_name=None,
        version="1.0.0",
        status="draft",
        owner_team_id=None,
        data_product=None,
        description_purpose="Governed order events.",
        description_usage=None,
        description_limitations=None,
        schema_objects=[SimpleNamespace(
            name="order_event",
            physical_type="table",
            logical_type="object",
            description="One row per event.",
            physical_name=None,
            properties=[SimpleNamespace(
                name="order_id",
                logical_type="string",
                required=True,
                primary_key=True,
                classification="confidential",
            )],
        )],
        servers=[],
        roles=[],
        sla_properties=[SimpleNamespace(property="freshness", value="15")],
        custom_properties=[SimpleNamespace(property="sourceOfTruth", value="ontos")],
        tags=[],
        created_at=None,
        updated_at=None,
    )

    resource = DataContractFileModel.wrap_as_resource(
        contract,
        DataContractFileModel.to_yaml_dict(contract),
    )

    assert resource["spec"]["schema"] == [{
        "name": "order_event",
        "type": "table",
        "description": "One row per event.",
        "columns": [{
            "name": "order_id",
            "type": "string",
            "primaryKey": True,
            "nullable": False,
            "classification": "confidential",
        }],
    }]
    assert resource["spec"]["sla"] == {"freshness": "15"}
    assert resource["spec"]["customProperties"] == {"sourceOfTruth": "ontos"}
