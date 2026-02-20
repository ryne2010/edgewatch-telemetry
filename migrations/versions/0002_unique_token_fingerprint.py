"""Make devices.token_fingerprint unique.

Revision ID: 0002_unique_token_fingerprint
Revises: 0001_initial
Create Date: 2026-02-19

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_unique_token_fingerprint"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Replace the non-unique index with a unique one.
    op.drop_index("ix_devices_token_fingerprint", table_name="devices")
    op.create_index(
        "ix_devices_token_fingerprint",
        "devices",
        ["token_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_devices_token_fingerprint", table_name="devices")
    op.create_index(
        "ix_devices_token_fingerprint",
        "devices",
        ["token_fingerprint"],
        unique=False,
    )
