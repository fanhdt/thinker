"""add telegram_chat_id to conversations

Revision ID: 042be516625b
Revises: 6ce8d55f3a62
Create Date: 2026-09-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '042be516625b'
down_revision: Union[str, Sequence[str], None] = '6ce8d55f3a62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'conversations',
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
    )
    op.create_unique_constraint(
        'uq_conversations_telegram_chat_id', 'conversations', ['telegram_chat_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_conversations_telegram_chat_id', 'conversations', type_='unique')
    op.drop_column('conversations', 'telegram_chat_id')
