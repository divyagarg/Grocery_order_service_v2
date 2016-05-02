"""empty message

Revision ID: c694253966a0
Revises: e9e595d146ac
Create Date: 2016-05-02 20:02:44.386549

"""

# revision identifiers, used by Alembic.
revision = 'c694253966a0'
down_revision = 'e9e595d146ac'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('address',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('mobile', sa.String(length=512), nullable=False),
    sa.Column('street_1', sa.String(length=512), nullable=False),
    sa.Column('street_2', sa.String(length=512), nullable=True),
    sa.Column('city', sa.String(length=512), nullable=False),
    sa.Column('pincode', sa.String(length=512), nullable=False),
    sa.Column('state', sa.String(length=512), nullable=False),
    sa.Column('email', sa.String(length=512), nullable=True),
    sa.Column('landmark', sa.String(length=512), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('cart',
    sa.Column('created_on', sa.DateTime(), server_default=sa.text(u'now()'), nullable=True),
    sa.Column('updated_on', sa.DateTime(), server_default=sa.text(u'now()'), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cart_reference_uuid', sa.String(length=255), nullable=False),
    sa.Column('geo_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('promo_codes', sa.String(length=255), nullable=True),
    sa.Column('total_offer_price', sa.Numeric(), nullable=True),
    sa.Column('total_discount', sa.Numeric(), nullable=True),
    sa.Column('total_display_price', sa.Numeric(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('cart__item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cart_item_id', sa.String(length=255), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('promo_codes', sa.String(length=255), nullable=True),
    sa.Column('offer_price', sa.Numeric(), nullable=True),
    sa.Column('display_price', sa.Numeric(), nullable=True),
    sa.Column('item_discount', sa.Numeric(), nullable=True),
    sa.Column('order_partial_discount', sa.Numeric(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('order__item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.String(length=255), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('display_price', sa.Numeric(), nullable=True),
    sa.Column('offer_price', sa.Numeric(), nullable=True),
    sa.Column('shipping_charge', sa.Numeric(), nullable=True),
    sa.Column('item_discount', sa.Numeric(), nullable=True),
    sa.Column('order_partial_discount', sa.Numeric(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('payment',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(), nullable=True),
    sa.Column('payment_transaction_id', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('order',
    sa.Column('created_on', sa.DateTime(), server_default=sa.text(u'now()'), nullable=True),
    sa.Column('updated_on', sa.DateTime(), server_default=sa.text(u'now()'), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_reference_id', sa.String(length=255), nullable=False),
    sa.Column('geo_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('promo_codes', sa.String(length=255), nullable=True),
    sa.Column('shipping_address', sa.Integer(), nullable=False),
    sa.Column('billing_address', sa.Integer(), nullable=True),
    sa.Column('delivery_type', sa.Enum('Normal', 'Slotted', name='delivery_types'), nullable=False),
    sa.Column('delivery_due_date', sa.Date(), nullable=True),
    sa.Column('freebie', sa.String(length=255), nullable=True),
    sa.Column('payment_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['billing_address'], ['address.id'], ),
    sa.ForeignKeyConstraint(['payment_id'], ['payment.id'], ),
    sa.ForeignKeyConstraint(['shipping_address'], ['address.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.drop_table('test')
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('test',
    sa.Column('id', mysql.INTEGER(display_width=11), nullable=False),
    sa.Column('name', mysql.VARCHAR(collation=u'utf8_bin', length=128), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate=u'utf8_bin',
    mysql_default_charset=u'utf8',
    mysql_engine=u'InnoDB'
    )
    op.drop_table('order')
    op.drop_table('payment')
    op.drop_table('order__item')
    op.drop_table('cart__item')
    op.drop_table('cart')
    op.drop_table('address')
    ### end Alembic commands ###
