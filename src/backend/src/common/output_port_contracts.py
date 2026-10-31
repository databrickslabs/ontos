"""The rule for publishing a data product: every output port needs an approved contract.

Shared by ``DataProductsManager.set_publication_scope`` and the workflow
``publish`` action, so both routes apply one rule and refuse with the same
coded error (``CodedValueError``: ``code`` and ``params`` next to the English
message).
"""
from typing import List

from src.common.api_errors import CodedValueError


class OutputPortContractsError(CodedValueError):
    """A product can't be published: an output port has no usable contract.

    ``ports`` (a text) lists the ports, or the ports with their contracts, that
    block the publication.
    """

    def __init__(self, message: str, ports: str):
        super().__init__(message, ports=ports)


class OutputPortContractsMissingError(OutputPortContractsError):
    """Output ports without a data contract."""

    code = 'output_port_contracts_missing'

    def __init__(self, ports: List[str]):
        names = ', '.join(ports)
        super().__init__(
            f"Cannot publish product: Output ports {names} must have data contracts assigned",
            names,
        )


class OutputPortContractsUnapprovedError(OutputPortContractsError):
    """Output ports whose contract is missing or isn't approved / active."""

    code = 'output_port_contracts_unapproved'

    def __init__(self, ports: List[str]):
        names = ', '.join(ports)
        super().__init__(
            f"Cannot publish product: These output ports have unapproved contracts: "
            f"{names}. Contracts must be approved first.",
            names,
        )


def validate_output_port_contracts(product_db, db) -> None:
    """Raise unless every output port of the product has an approved / active contract.

    Used by ``set_publication_scope`` and by the workflow ``publish`` action, so
    both routes apply one rule.
    """
    if not product_db.output_ports:
        return
    ports_without_contracts = [
        port.name for port in product_db.output_ports
        if not port.contract_id
    ]
    if ports_without_contracts:
        raise OutputPortContractsMissingError(ports_without_contracts)

    from src.repositories.data_contracts_repository import data_contract_repo

    valid_contract_statuses = ['approved', 'active']
    contracts_not_approved = []

    for port in product_db.output_ports:
        if port.contract_id:
            contract = data_contract_repo.get(db=db, id=port.contract_id)
            if not contract:
                contracts_not_approved.append(
                    f"{port.name} -> {port.contract_id} (contract not found)"
                )
                continue
            contract_status = (contract.status or '').lower()
            if contract_status not in valid_contract_statuses:
                contracts_not_approved.append(
                    f"{port.name} -> {contract.name} (status: {contract.status})"
                )

    if contracts_not_approved:
        raise OutputPortContractsUnapprovedError(contracts_not_approved)
