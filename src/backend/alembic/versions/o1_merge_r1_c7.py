"""merge r1_role_hidden_nav_features and c7_metric_view_change_requests heads

c7 revises b9_lifecycle_deprecation_fields; r1 (#1326) follows b10 on the same b9.
No schema change.

Revision ID: o1_merge_r1_c7
Revises: r1_role_hidden_nav_features, c7_metric_view_change_requests
Create Date: 2026-11-09 17:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'o1_merge_r1_c7'
down_revision: Union[str, Sequence[str], None] = (
    'r1_role_hidden_nav_features',
    'c7_metric_view_change_requests',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
