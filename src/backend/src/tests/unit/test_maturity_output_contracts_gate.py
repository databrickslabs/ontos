"""The "Has output contracts" maturity gate follows the output ports' own contracts.

``has_contract`` used to count the input contracts of the output ports (the contracts a
port is built from), so a product with a contract on its output port failed the gate and
a product with only input contracts passed it.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest

from src.common.compliance_dsl import evaluate_rule_on_object
from src.controller.entity_dict_builder import build_data_product_dict
from src.db_models.data_products import DataProductDb, InputContractDb, OutputPortDb

GATE_RULE = 'ASSERT obj.has_contract = True'


def _product(db, contract_id=None, input_contracts=0):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name='p', version='1.0.0',
    )
    db.add(product)
    db.flush()
    port = OutputPortDb(
        id=str(uuid.uuid4()), product_id=product.id, name='orders', version='1.0.0',
        contract_id=contract_id,
    )
    db.add(port)
    db.flush()
    for i in range(input_contracts):
        db.add(InputContractDb(
            id=str(uuid.uuid4()), output_port_id=port.id,
            contract_id=f'in-{i}', contract_version='1.0.0',
        ))
    db.flush()
    db.expire_all()
    return product


def _gate_passes(db, product):
    obj = build_data_product_dict(db, product.id)
    return evaluate_rule_on_object(GATE_RULE, obj)[0]


@pytest.mark.parametrize('contract_id, input_contracts, passed', [
    ('contract-1', 0, True),
    (None, 2, False),
    ('contract-1', 2, True),
    (None, 0, False),
])
def test_gate_follows_the_output_port_contract(db_session, contract_id, input_contracts, passed):
    product = _product(db_session, contract_id=contract_id, input_contracts=input_contracts)

    assert _gate_passes(db_session, product) is passed

