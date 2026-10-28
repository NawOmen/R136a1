"""Buyer supplier board, conversations and locally processed reply files."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 creates current metadata on a fresh install; keep upgrades repeat-safe.
    op.create_table("supplier_requests",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("need_id", pg.UUID(as_uuid=True), sa.ForeignKey("marketplace.needs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("need_revision", sa.Integer(), nullable=False),
        sa.Column("buyer_company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_company_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_name", sa.String(255), nullable=False), sa.Column("seller_name", sa.String(255), nullable=False),
        sa.Column("specification", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("quoted_price_rub", sa.Numeric(24, 12)),
        sa.Column("price_basis", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("lead_time_days", sa.Integer()), sa.Column("delivery_date", sa.Date()),
        sa.Column("note", sa.String(2000), nullable=False, server_default=""),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("need_id", "need_revision", "seller_company_id", name="uq_supplier_request_version"),
        sa.CheckConstraint("status IN ('draft','sent','replied','selected')", name="ck_supplier_request_status"), schema="marketplace", if_not_exists=True)
    for column in ("need_id", "buyer_company_id", "seller_company_id"):
        op.create_index(f"ix_marketplace_supplier_requests_{column}", "supplier_requests", [column], schema="marketplace", if_not_exists=True)
    op.create_table("supplier_request_messages",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", pg.UUID(as_uuid=True), sa.ForeignKey("marketplace.supplier_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_company_id", pg.UUID(as_uuid=True), nullable=False), sa.Column("author_user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False), sa.Column("message", sa.String(6000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", "author_company_id", "request_key", name="uq_supplier_message_request"), schema="marketplace", if_not_exists=True)
    op.create_index("ix_marketplace_supplier_request_messages_request_id", "supplier_request_messages", ["request_id"], schema="marketplace", if_not_exists=True)
    op.create_table("supplier_reply_files",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", pg.UUID(as_uuid=True), sa.ForeignKey("marketplace.supplier_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False), sa.Column("file_key", sa.String(500), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", "content_hash", name="uq_supplier_reply_content"), schema="marketplace", if_not_exists=True)
    op.create_index("ix_marketplace_supplier_reply_files_request_id", "supplier_reply_files", ["request_id"], schema="marketplace", if_not_exists=True)


def downgrade():
    for table in ("supplier_reply_files", "supplier_request_messages", "supplier_requests"):
        op.drop_table(table, schema="marketplace")
