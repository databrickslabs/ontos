"""The MCP / Ask Ontos product and contract tools take any stage key as status.

A custom Lifecycle Stage Group has its own stage keys, so a fixed enum would make
them unreachable; the update tools check the move through the lifecycle service
(``transition_status``), and the filters match the stored key.
"""
import pytest

from src.tools.data_contracts import (
    ListDataContractsTool, SearchDataContractsTool, UpdateDataContractTool,
)
from src.tools.data_products import (
    ListDataProductsTool, SearchDataProductsTool, UpdateDataProductTool,
)


@pytest.mark.parametrize('tool', [
    SearchDataProductsTool, UpdateDataProductTool, ListDataProductsTool,
    SearchDataContractsTool, UpdateDataContractTool, ListDataContractsTool,
])
def test_the_status_parameter_has_no_fixed_enum(tool):
    status = tool.parameters['status']
    assert status['type'] == 'string'
    assert 'enum' not in status
    assert 'stage' in status['description']
