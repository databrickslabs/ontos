"""
Regression tests for OutputPort.delivery_method_id persistence.

Pins the contract for `DataProductRepository.update()` output-port upsert:

- Updating an existing port WITHOUT the `delivery_method_id` key in the payload
  preserves the prior FK value (defensive guard — partial UI updates must not
  silently clobber the FK).
- Updating an existing port WITH `delivery_method_id` explicitly None clears
  the FK (caller-driven clear).
- Updating an existing port WITH a new `delivery_method_id` writes the new FK.
- Creating a new port WITH `delivery_method_id` persists the FK.
- Creating a new port WITHOUT the `delivery_method_id` key leaves it NULL.

The guard in `update()` keys off `'delivery_method_id' in port_dict` rather than
`port_dict.get('delivery_method_id') is not None`, so the "explicit null
clears" semantics survive `model_dump(exclude_unset=True, by_alias=True)`
round-trips.

Note on test substrate: the test harness uses in-memory SQLite, which is
incompatible with the production `PG_UUID(as_uuid=True)` column type used for
`OutputPortDb.delivery_method_id` (binder calls `.hex` on the bound value).
Existing tests in this repo handle this by mocking (see
`test_business_role_approvers.py:183`). Here we sidestep the column type
entirely by asserting on the in-memory SQLAlchemy ORM attribute set by
`update()` — which is exactly the field the production bug is about. The
attribute is set in Python by `port_obj.delivery_method_id = ...`; the SQL
INSERT/UPDATE that follows is irrelevant for this regression.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from src.db_models.data_products import DataProductDb, OutputPortDb
from src.repositories.data_products_repository import data_product_repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_product_with_port(initial_dm_id: str | None) -> tuple[DataProductDb, OutputPortDb]:
    """Build an in-memory DataProductDb with one OutputPortDb pre-populated.

    We do NOT persist via the session — the test only inspects in-memory ORM
    attribute mutations made by `update()`.
    """
    product = DataProductDb(
        id=str(uuid.uuid4()),
        name="DM Round-Trip Product",
        version="1.0.0",
        status="draft",
    )
    port = OutputPortDb(
        id=str(uuid.uuid4()),
        name="seeded-port",
        version="1.0.0",
        delivery_method_id=initial_dm_id,
    )
    product.output_ports.append(port)
    return product, port


def _stub_session() -> MagicMock:
    """A SQLAlchemy Session stub that satisfies the repo's `db.delete(...)`
    contract without actually executing SQL.
    """
    return MagicMock(name="db_session")


# ---------------------------------------------------------------------------
# Update-side coverage — the regression these tests are here for
# ---------------------------------------------------------------------------


class TestOutputPortDeliveryMethodOnUpdate:
    """`update()` must not clobber `delivery_method_id` on partial payloads."""

    def test_update_omitting_key_preserves_existing_fk(self):
        """Payload without `delivery_method_id` must NOT NULL out the FK."""
        original_dm_id = str(uuid.uuid4())
        product, port = _make_db_product_with_port(initial_dm_id=original_dm_id)

        # Simulate a partial UI update that only changes the name/version. The
        # `delivery_method_id` key is deliberately absent — this mirrors the
        # dict produced by `model_dump(exclude_unset=True, by_alias=True)` when
        # the FE form does not surface the delivery-method field.
        update_payload = {
            "output_ports": [
                {
                    "id": port.id,
                    "name": "seeded-port-renamed",
                    "version": "1.0.1",
                }
            ]
        }
        data_product_repo.update(
            db=_stub_session(), db_obj=product, obj_in=update_payload
        )

        assert port.delivery_method_id == original_dm_id
        assert port.name == "seeded-port-renamed"
        assert port.version == "1.0.1"

    def test_update_with_explicit_null_clears_fk(self):
        """Payload with `delivery_method_id: None` must clear the FK."""
        original_dm_id = str(uuid.uuid4())
        product, port = _make_db_product_with_port(initial_dm_id=original_dm_id)

        update_payload = {
            "output_ports": [
                {
                    "id": port.id,
                    "name": "seeded-port",
                    "version": "1.0.0",
                    "delivery_method_id": None,
                }
            ]
        }
        data_product_repo.update(
            db=_stub_session(), db_obj=product, obj_in=update_payload
        )

        assert port.delivery_method_id is None

    def test_update_with_new_value_overwrites_fk(self):
        """Payload with a different `delivery_method_id` must overwrite."""
        original_dm_id = str(uuid.uuid4())
        new_dm_id = str(uuid.uuid4())
        product, port = _make_db_product_with_port(initial_dm_id=original_dm_id)

        update_payload = {
            "output_ports": [
                {
                    "id": port.id,
                    "name": "seeded-port",
                    "version": "1.0.0",
                    "delivery_method_id": new_dm_id,
                }
            ]
        }
        data_product_repo.update(
            db=_stub_session(), db_obj=product, obj_in=update_payload
        )

        assert port.delivery_method_id == new_dm_id


# ---------------------------------------------------------------------------
# Create-side coverage (new ports inside update())
# ---------------------------------------------------------------------------


class TestOutputPortDeliveryMethodOnCreateInUpdate:
    """`update()` must persist `delivery_method_id` on newly-added ports."""

    def test_new_port_with_delivery_method_persists_fk(self):
        new_dm_id = str(uuid.uuid4())
        product = DataProductDb(
            id=str(uuid.uuid4()),
            name="DM Round-Trip Product",
            version="1.0.0",
            status="draft",
        )

        update_payload = {
            "output_ports": [
                {
                    "name": "new-port-with-dm",
                    "version": "1.0.0",
                    "delivery_method_id": new_dm_id,
                }
            ]
        }
        data_product_repo.update(
            db=_stub_session(), db_obj=product, obj_in=update_payload
        )

        assert len(product.output_ports) == 1
        assert product.output_ports[0].delivery_method_id == new_dm_id

    def test_new_port_without_delivery_method_persists_null(self):
        product = DataProductDb(
            id=str(uuid.uuid4()),
            name="DM Round-Trip Product",
            version="1.0.0",
            status="draft",
        )

        update_payload = {
            "output_ports": [
                {
                    "name": "new-port-no-dm",
                    "version": "1.0.0",
                }
            ]
        }
        data_product_repo.update(
            db=_stub_session(), db_obj=product, obj_in=update_payload
        )

        assert len(product.output_ports) == 1
        assert product.output_ports[0].delivery_method_id is None
