"""Auto-generated migration draft for KeelModel. Review before applying."""

from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("sales_customer",
        sa.Column("name", sa.Text(), nullable=False, primary_key=False),
        sa.Column("email", sa.Text(), nullable=True, primary_key=False),
        sa.Column("tax_id", sa.Text(), nullable=True, primary_key=False),
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint('email'),
    )
    op.create_table("sales_invoice",
        sa.Column("number", sa.Text(), nullable=False, primary_key=False),
        sa.Column("status", sa.Text(), nullable=False, primary_key=False, server_default='draft'),
        sa.Column("total", sa.Numeric(), nullable=False, primary_key=False, server_default=0),
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("sales_customer.id", ondelete="RESTRICT"), nullable=False),
        sa.UniqueConstraint('number'),
    )
    op.create_table("sales_invoice_line",
        sa.Column("description", sa.Text(), nullable=False, primary_key=False),
        sa.Column("quantity", sa.Integer(), nullable=False, primary_key=False, server_default=1),
        sa.Column("unit_price", sa.Numeric(), nullable=False, primary_key=False),
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("sales_invoice.id", ondelete="CASCADE"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sales_invoice_line")
    op.drop_table("sales_invoice")
    op.drop_table("sales_customer")
