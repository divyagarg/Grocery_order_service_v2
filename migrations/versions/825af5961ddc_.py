"""empty message

Revision ID: 825af5961ddc
Revises: 69a04e717ce3
Create Date: 2016-05-20 21:15:41.257628

"""

# revision identifiers, used by Alembic.
revision = '825af5961ddc'
down_revision = '69a04e717ce3'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(u'payment_ibfk_1', 'payment', type_='foreignkey')
    op.create_foreign_key(None, 'payment', 'order', ['order_id'], ['parent_order_id'])
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'payment', type_='foreignkey')
    op.create_foreign_key(u'payment_ibfk_1', 'payment', 'order', ['order_id'], ['order_reference_id'])
    ### end Alembic commands ###