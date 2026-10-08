"""Durable agent task-contract: states, retries, cache (stage S04)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS model_version VARCHAR(120)")
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(64)")
    op.execute("ALTER TABLE agents.agent_runs ADD COLUMN IF NOT EXISTS provider_kind VARCHAR(16)")
    op.execute("ALTER TABLE agents.tool_calls ADD COLUMN IF NOT EXISTS executor VARCHAR(16)")
    # 0001 создаёт таблицы через create_all по текущим моделям, поэтому на новой
    # базе таблицы уже есть; на существующей их создаёт эта миграция.
    has_tasks = sa.inspect(op.get_bind()).has_table("agent_tasks", schema="agents")
    has_cache = sa.inspect(op.get_bind()).has_table("agent_task_cache", schema="agents")
    if has_tasks and has_cache:
        return
    if not has_tasks:
        op.create_table("agent_tasks",
            sa.Column("task_id", UUID(as_uuid=True), primary_key=True),
            sa.Column("parent_task_id", UUID(as_uuid=True),
                      sa.ForeignKey("agents.agent_tasks.task_id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("company_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("actor_user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("scenario_type", sa.String(64), nullable=False),
            sa.Column("input_revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("model_version", sa.String(120), nullable=True),
            sa.Column("prompt_version", sa.String(64), nullable=True),
            sa.Column("schema_version", sa.String(64), nullable=True),
            sa.Column("source_refs", JSONB, nullable=False, server_default="[]"),
            sa.Column("state", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("current_step", sa.String(500), nullable=False, server_default=""),
            sa.Column("required_response", JSONB, nullable=True),
            sa.Column("result_artifact", JSONB, nullable=True),
            sa.Column("approval", JSONB, nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("linked_run_id", UUID(as_uuid=True),
                      sa.ForeignKey("agents.agent_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "idempotency_key", name="uq_agent_tasks_company_key"),
            schema="agents")
    if not has_cache:
        op.create_table("agent_task_cache",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("cache_key", sa.String(200), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("source_versions_hash", sa.String(64), nullable=False),
            sa.Column("run_id", UUID(as_uuid=True),
                      sa.ForeignKey("agents.agent_runs.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("source_ids", JSONB, nullable=False, server_default="[]"),
            sa.Column("payload", JSONB, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "cache_key", "input_hash", "source_versions_hash",
                                name="uq_agent_task_cache_binding"),
            schema="agents")


def downgrade():
    op.drop_table("agent_task_cache", schema="agents")
    op.drop_table("agent_tasks", schema="agents")
    op.drop_column("tool_calls", "executor", schema="agents")
    op.drop_column("agent_runs", "provider_kind", schema="agents")
    op.drop_column("agent_runs", "prompt_version", schema="agents")
    op.drop_column("agent_runs", "model_version", schema="agents")
