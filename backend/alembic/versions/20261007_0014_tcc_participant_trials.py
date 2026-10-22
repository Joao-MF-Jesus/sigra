"""Participant credentials, opaque sessions and immutable TCC test records.

Revision ID: 20261007_0014
Revises: 20261005_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20261007_0014"
down_revision = "20261005_0013"
branch_labels = None
depends_on = None


def upgrade():
    # Legacy accounts are preserved, not activated and not assigned passwords.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("normalized_email", sa.String(160), nullable=True))
        batch.add_column(sa.Column("password_hash", sa.String(255), nullable=True))
        batch.add_column(sa.Column("role", sa.String(20), nullable=False, server_default="participant"))
        batch.create_unique_constraint("uq_users_normalized_email", ["normalized_email"])
        batch.create_check_constraint("ck_users_role", "role IN ('participant', 'admin')")
    op.create_table("auth_sessions",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table("participant_test_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_version", sa.String(80), nullable=False),
        sa.Column("method_version", sa.String(160), nullable=False),
        sa.Column("snapshot_version", sa.String(80), nullable=True),
        sa.Column("snapshot_fingerprint", sa.String(64), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("presented_results", sa.JSON(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_fingerprint", sa.String(64), nullable=False),
        sa.Column("feedback_rating", sa.Integer(), nullable=True),
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("feedback_rating IS NULL OR feedback_rating BETWEEN 1 AND 5", name="ck_test_run_rating"))
    op.create_index("ix_test_runs_owner_created", "participant_test_runs", ["user_id", "created_at", "id"])


def downgrade():
    bind = op.get_bind()
    for table in ("auth_sessions", "participant_test_runs"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError("Downgrade blocked: preserve participant sessions and test history")
    if bind.execute(sa.text("SELECT COUNT(*) FROM users WHERE password_hash IS NOT NULL OR role != 'participant'")).scalar_one():
        raise RuntimeError("Downgrade blocked: preserve participant credentials")
    op.drop_index("ix_test_runs_owner_created", table_name="participant_test_runs")
    op.drop_table("participant_test_runs")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role", type_="check")
        batch.drop_constraint("uq_users_normalized_email", type_="unique")
        batch.drop_column("role")
        batch.drop_column("password_hash")
        batch.drop_column("normalized_email")
