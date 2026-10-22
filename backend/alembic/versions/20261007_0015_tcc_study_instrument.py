"""Additive Appendix C/D instrument. Does not modify the approved V6 or 0014."""
from alembic import op
import sqlalchemy as sa

revision = "20261007_0015"
down_revision = "20261007_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("participant_study_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("auth_session_digest", sa.String(64), sa.ForeignKey("auth_sessions.token_digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("scenario_id", sa.String(1), nullable=False),
        sa.Column("familiarity", sa.String(10), nullable=False),
        sa.Column("priorities", sa.JSON(), nullable=False),
        sa.Column("protocol_version", sa.String(80), nullable=False),
        sa.Column("presentation_version", sa.String(80), nullable=False),
        sa.Column("environment_tag", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scenario_id IN ('A','B','C','D','E')", name="ck_study_scenario"),
        sa.CheckConstraint("familiarity IN ('none','low','medium','high')", name="ck_study_familiarity"))
    op.create_index("ix_study_owner_auth_created", "participant_study_sessions", ["user_id", "auth_session_digest", "created_at"])
    with op.batch_alter_table("participant_test_runs") as batch:
        batch.add_column(sa.Column("study_session_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("technical_record", sa.JSON(), nullable=True))
        batch.create_foreign_key("fk_test_run_study", "participant_study_sessions", ["study_session_id"], ["id"], ondelete="RESTRICT")
    op.create_table("participant_questionnaires",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("participant_test_runs.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("version", sa.String(80), nullable=False),
        *(sa.Column(name, sa.Integer(), nullable=False) for name in
          ("interface_clarity", "first_vehicle_explanation", "scenario_coherence", "influential_criteria")),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        *(sa.CheckConstraint(f"{name} BETWEEN 1 AND 5", name=f"ck_questionnaire_{name}") for name in
          ("interface_clarity", "first_vehicle_explanation", "scenario_coherence", "influential_criteria")))


def downgrade():
    bind = op.get_bind()
    for table in ("participant_study_sessions", "participant_questionnaires"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError("Downgrade blocked: preserve Appendix C/D research records")
    if bind.execute(sa.text("SELECT COUNT(*) FROM participant_test_runs WHERE study_session_id IS NOT NULL OR technical_record IS NOT NULL")).scalar_one():
        raise RuntimeError("Downgrade blocked: preserve technical execution records")
    op.drop_table("participant_questionnaires")
    with op.batch_alter_table("participant_test_runs") as batch:
        batch.drop_constraint("fk_test_run_study", type_="foreignkey")
        batch.drop_column("technical_record")
        batch.drop_column("study_session_id")
    op.drop_index("ix_study_owner_auth_created", table_name="participant_study_sessions")
    op.drop_table("participant_study_sessions")
