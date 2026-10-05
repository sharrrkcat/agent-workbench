"""Add shared gallery metadata without touching attachment files."""
from alembic import op
import sqlalchemy as sa

revision = "0040_qq_resources"
down_revision = "0039_qq_icebreaker"
branch_labels = None
depends_on = None


def upgrade():
    sequence = op.get_bind().exec_driver_sql("SELECT coalesce(max(seq), 0) FROM sqlite_sequence WHERE name = 'qq_media_assets'").scalar_one()
    # SQLite needs a table rebuild for a timestamp default. Existing resources
    # receive the upgrade time; their original acquisition dates are not inferred.
    with op.batch_alter_table("qq_media_assets", recreate="always", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("description_manual", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    # Rebuilding an empty table must not reuse ids belonging to deleted resources.
    op.execute("DELETE FROM sqlite_sequence WHERE name = 'qq_media_assets'")
    op.execute(sa.text("INSERT INTO sqlite_sequence (name, seq) VALUES ('qq_media_assets', :sequence)").bindparams(sequence=sequence))


def downgrade():
    raise RuntimeError("Test database downgrade is unsupported")
