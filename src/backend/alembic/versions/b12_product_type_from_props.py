"""move productType custom properties onto data_products.product_type_id

Before b11 a product's type was only a free-text ``productType`` custom
property. This moves each product's value onto the new foreign key and then
deletes the custom property rows.

Values are normalised to type keys before lookup: surrounding JSON quotes are
removed, camelCase is split, and spaces/underscores become hyphens, so
``sourceAligned``, ``"source-aligned"``, ``Source Aligned`` and
``SOURCE_ALIGNED`` all become ``source-aligned``. A value that matches no
existing type gets a new active type with that key, flagged ``is_imported``,
so no product loses its type.

When a product has several ``productType`` rows, the first one with a usable
value wins. A product that already has a ``product_type_id`` keeps it. Empty
values are just deleted. Running it twice is a no-op.

Downgrade writes the type keys back as ``productType`` custom properties (for
products that don't have one) and clears the foreign key. Types created here
are left in place; b11's downgrade drops the table.

Revision ID: b12_product_type_from_props
Revises: b11_data_product_types
Create Date: 2026-11-16 12:00:00.000000

"""

import json
import logging
import re
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers, used by Alembic.
revision: str = "b12_product_type_from_props"
down_revision: str | None = "b11_data_product_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

PROPERTY = "productType"
_KEY_MAX = 100
_LABEL_MAX = 255

data_product_types = sa.table(
    "data_product_types",
    sa.column("id", PG_UUID(as_uuid=True)),
    sa.column("key", sa.String()),
    sa.column("label", sa.String()),
    sa.column("description", sa.Text()),
    sa.column("sort_order", sa.Integer()),
    sa.column("is_active", sa.Boolean()),
    sa.column("is_default", sa.Boolean()),
    sa.column("is_imported", sa.Boolean()),
)
data_products = sa.table(
    "data_products",
    sa.column("id", sa.String()),
    sa.column("product_type_id", PG_UUID(as_uuid=True)),
)
custom_properties = sa.table(
    "data_product_custom_properties",
    sa.column("id", sa.String()),
    sa.column("product_id", sa.String()),
    sa.column("property", sa.String()),
    sa.column("value", sa.Text()),
)


def _strip_json_quotes(value: str) -> str:
    """``"sink"`` (a JSON-encoded string, as older rows were stored) -> ``sink``."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        if isinstance(decoded, str):
            return decoded.strip()
    return value


def label_for(raw: str | None) -> str | None:
    """The stored value without JSON quotes or surrounding whitespace."""
    if raw is None:
        return None
    return _strip_json_quotes(raw.strip()) or None


def normalize_type_key(raw: str | None) -> str | None:
    """Turn a stored productType value into a type key, or None if it's empty."""
    value = label_for(raw)
    if value is None:
        return None
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)  # sourceAligned -> source-Aligned
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:_KEY_MAX].rstrip("-") or None


def upgrade() -> None:
    bind = op.get_bind()

    rows = bind.execute(
        sa.select(
            custom_properties.c.id,
            custom_properties.c.product_id,
            custom_properties.c.value,
        )
        .where(sa.func.lower(custom_properties.c.property) == PROPERTY.lower())
        .order_by(custom_properties.c.product_id, custom_properties.c.id)
    ).all()
    if not rows:
        return

    types_by_key = {
        key: type_id
        for type_id, key in bind.execute(sa.select(data_product_types.c.id, data_product_types.c.key))
    }
    next_order = (
        bind.execute(sa.select(sa.func.max(data_product_types.c.sort_order))).scalar() or 0
    ) + 1
    typed_products = {
        product_id
        for (product_id,) in bind.execute(
            sa.select(data_products.c.id).where(data_products.c.product_type_id.isnot(None))
        )
    }

    assigned = created = 0
    for _, product_id, raw in rows:
        if product_id in typed_products:
            continue
        key = normalize_type_key(raw)
        if key is None:
            continue

        type_id = types_by_key.get(key)
        if type_id is None:
            type_id = uuid4()
            bind.execute(
                data_product_types.insert().values(
                    id=type_id,
                    key=key,
                    label=(label_for(raw) or key)[:_LABEL_MAX],
                    description="Created from existing data products during upgrade",
                    sort_order=next_order,
                    is_active=True,
                    is_default=False,
                    is_imported=True,
                )
            )
            types_by_key[key] = type_id
            next_order += 1
            created += 1

        bind.execute(
            data_products.update()
            .where(data_products.c.id == product_id)
            .values(product_type_id=type_id)
        )
        typed_products.add(product_id)
        assigned += 1

    bind.execute(
        custom_properties.delete().where(
            custom_properties.c.id.in_([row_id for row_id, _, _ in rows])
        )
    )
    logger.info(
        "b12: set product_type_id on %d data product(s), created %d imported type(s), "
        "removed %d productType custom propert(ies)",
        assigned,
        created,
        len(rows),
    )


def downgrade() -> None:
    bind = op.get_bind()

    has_property = {
        product_id
        for (product_id,) in bind.execute(
            sa.select(custom_properties.c.product_id).where(
                sa.func.lower(custom_properties.c.property) == PROPERTY.lower()
            )
        )
    }
    typed = bind.execute(
        sa.select(data_products.c.id, data_product_types.c.key).join(
            data_product_types, data_products.c.product_type_id == data_product_types.c.id
        )
    ).all()

    restored = [
        {"id": str(uuid4()), "product_id": product_id, "property": PROPERTY, "value": key}
        for product_id, key in typed
        if product_id not in has_property
    ]
    if restored:
        bind.execute(custom_properties.insert(), restored)
    bind.execute(
        data_products.update()
        .where(data_products.c.product_type_id.isnot(None))
        .values(product_type_id=None)
    )
