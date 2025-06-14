# File: migrations/versions/add_conversation_system.py
"""add conversation system

Revision ID: conv_001
Revises: 685fd5cae1c1
Create Date: 2025-06-09 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'conv_001'
down_revision: Union[str, None] = '685fd5cae1c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Add conversation history and user preferences tables"""
    
    # Conversation History Table
    op.create_table(
        'conversation_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('response', sa.Text(), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('intent', sa.String(50), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('session_id', sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # User Preferences Table
    op.create_table(
        'user_preferences',
        sa.Column('user_id', sa.String(50), nullable=False),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True, default='{}'),
        sa.Column('learned_patterns', postgresql.JSONB(astext_type=sa.Text()), nullable=True, default='{}'),
        sa.Column('service_weights', postgresql.JSONB(astext_type=sa.Text()), nullable=True, default='{}'),
        sa.Column('communication_style', sa.String(20), nullable=True, default='enthusiastic'),
        sa.Column('preferred_response_length', sa.String(10), nullable=True, default='medium'),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('user_id')
    )
    
    # Create indexes for performance
    op.create_index('idx_conversation_user_timestamp', 'conversation_history', ['user_id', 'timestamp'])
    op.create_index('idx_conversation_session', 'conversation_history', ['session_id'])

def downgrade() -> None:
    """Remove conversation system tables"""
    op.drop_index('idx_conversation_session', table_name='conversation_history')
    op.drop_index('idx_conversation_user_timestamp', table_name='conversation_history')
    op.drop_table('user_preferences')
    op.drop_table('conversation_history')