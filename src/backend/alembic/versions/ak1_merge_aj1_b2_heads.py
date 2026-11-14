"""merge aj1_authority_team_project and b2_contract_deploy_default heads

Joins the Authority Resolution chain (branched off l1_entity_domain_associations)
with development's chain. A merge revision rather than re-pointing aa1: DBs
already stamped on the ARF chain must still replay development's migrations.

Revision ID: ak1_merge_aj1_b2
Revises: aj1_authority_team_project, b2_contract_deploy_default
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ak1_merge_aj1_b2'
down_revision: Union[str, None] = ('aj1_authority_team_project', 'b2_contract_deploy_default')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
