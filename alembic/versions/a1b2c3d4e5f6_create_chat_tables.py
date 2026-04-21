"""create_chat_tables

Revision ID: a1b2c3d4e5f6
Revises: d258688090c7
Create Date: 2026-04-20

Tables
------
conversations
    id          UUID PK
    type        VARCHAR(10)  default 'dm'
    status      VARCHAR(20)  default 'requested'  (requested|active|blocked)
    created_at  TIMESTAMP WITH TZ
    updated_at  TIMESTAMP WITH TZ

conversation_members
    conversation_id  UUID FK → conversations.id  CASCADE
    user_id          UUID FK → users.id  CASCADE
    last_read_at     TIMESTAMP WITH TZ  nullable
    is_muted         BOOLEAN  default false
    joined_at        TIMESTAMP WITH TZ
    PK (conversation_id, user_id)

messages
    id              UUID PK
    context_type    VARCHAR(10)   'dm' | 'group'
    context_id      UUID          conversations.id or groups.id
    sender_id       UUID FK → users.id  CASCADE
    message_type    VARCHAR(20)   default 'text'
    body            TEXT  nullable
    media_url       VARCHAR(500)  nullable
    media_metadata  JSONB  nullable
    location_lat    FLOAT  nullable
    location_lon    FLOAT  nullable
    reply_to_id     UUID FK → messages.id  SET NULL  nullable
    is_deleted      BOOLEAN  default false
    created_at      TIMESTAMP WITH TZ
    INDEX (context_type, context_id, created_at DESC)

chat_attachments
    id            UUID PK
    message_id    UUID FK → messages.id  CASCADE
    context_type  VARCHAR(10)
    context_id    UUID
    media_type    VARCHAR(20)
    media_url     VARCHAR(500)
    created_at    TIMESTAMP WITH TZ
    INDEX (context_type, context_id)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d258688090c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── conversations ──────────────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("type", sa.String(10), nullable=False, server_default="dm"),
        sa.Column("status", sa.String(20), nullable=False, server_default="requested"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── conversation_members ───────────────────────────────────────────────────
    op.create_table(
        "conversation_members",
        sa.Column(
            "conversation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_muted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "user_id"),
    )

    # Index — "list my conversations" is the hot path
    op.create_index(
        "idx_conversation_members_user",
        "conversation_members",
        ["user_id"],
    )

    # ── messages ───────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("context_type", sa.String(10), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "message_type", sa.String(20), nullable=False, server_default="text"
        ),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("media_url", sa.String(500), nullable=True),
        sa.Column("media_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("location_lat", sa.Float(), nullable=True),
        sa.Column("location_lon", sa.Float(), nullable=True),
        sa.Column("reply_to_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reply_to_id"], ["messages.id"], ondelete="SET NULL"
        ),
    )

    # Primary query: "give me messages for this conversation, newest first"
    op.create_index(
        "idx_messages_context",
        "messages",
        ["context_type", "context_id", sa.text("created_at DESC")],
    )

    # ── chat_attachments ───────────────────────────────────────────────────────
    op.create_table(
        "chat_attachments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_type", sa.String(10), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.String(20), nullable=False),
        sa.Column("media_url", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
    )

    # Index — shared media gallery query
    op.create_index(
        "idx_chat_attachments_context",
        "chat_attachments",
        ["context_type", "context_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_chat_attachments_context", table_name="chat_attachments")
    op.drop_table("chat_attachments")
    op.drop_index("idx_messages_context", table_name="messages")
    op.drop_table("messages")
    op.drop_index("idx_conversation_members_user", table_name="conversation_members")
    op.drop_table("conversation_members")
    op.drop_table("conversations")
