import config

__author__ = 'divyagarg'
import datetime
import logging
import json
import uuid

from apps.app_v1.api import parse_request_data, RequiredFieldMissing, EmptyCartException, IncorrectDataException, \
	CouponInvalidException, SubscriptionNotFoundException, QuantityNotAvailableException, get_shipping_charges
from apps.app_v1.api.api_schema_signature import CREATE_CART_SCHEMA
from apps.app_v1.models import order_types, payment_modes_dict
from apps.app_v1.models.models import Cart, CartItem, Address, OrderShipmentDetail
from utils.jsonutils.output_formatter import create_error_response, create_data_response
from utils.jsonutils.json_schema_validator import validate
from config import APP_NAME
import requests
from flask import g, current_app
from apps.app_v1.models.models import db
from apps.app_v1.api import ERROR



Logger = logging.getLogger(APP_NAME)


def check_if_calculate_price_api_response_is_correct_or_quantity_is_available(item, json_order_item):
	if json_order_item is None:
		Logger.error(
			"[%s] No item is found in calculate price API response for the item [%s]" %(g.UUID, item['item_uuid']),
			exc_info=True)
		raise SubscriptionNotFoundException(ERROR.SUBSCRIPTION_NOT_FOUND)
	if json_order_item['maxQuantity'] is not None and json_order_item['maxQuantity']< item['quantity']:
		Logger.error("[%s] Quantity requested can not be fulfilled for the item [%s]" %(g.UUID, item['item_uuid']),
			exc_info=True)
		raise QuantityNotAvailableException(ERROR.PRODUCT_AVAILABILITY_CHANGED)


class CartService:
	def __init__(self):
		"""

		:type self: object
		"""
		self.cart_reference_uuid = None
		self.total_price = 0.0
		self.total_discount = 0.0
		self.total_display_price = 0.0
		self.now = datetime.datetime.utcnow()

		self.total_shipping_charges = 0.0
		self.benefits = None
		self.cart_items = None
		self.is_cart_empty = False
		self.item_id_to_existing_item_dict = None
		self.deleted_cart_items = None
		self.shipping_address = None

	def create_or_update_cart(self, body):
		try:
			request_data = parse_request_data(body)
			validate(request_data, CREATE_CART_SCHEMA)
			cart = self.get_cart_for_geo_user_id(request_data['data'])
			if cart is not None:
				return self.update_cart(cart, request_data['data'])
			else:
				return self.create_cart(request_data['data'])
		except IncorrectDataException as ide:
			Logger.error("[%s] Validation Error [%s]" % (g.UUID, str(ide.message)))
			return create_error_response(ide)
		except Exception as e:
			Logger.error('[%s] Exception occured while creating/updating cart [%s]' % (g.UUID, str(e)), exc_info=True)
			ERROR.INTERNAL_ERROR.message = str(e)
			return create_error_response(ERROR.INTERNAL_ERROR)

	def get_cart_for_geo_user_id(self, data):
		return Cart().query.filter_by(geo_id=int(data['geo_id']), user_id=data['user_id']).first()

	def update_cart(self, cart, data):
		error = True
		err = None
		while True:
			# 1 Item update(Added, removed, update)
			try:
				self.update_cart_items(data, cart)

			except IncorrectDataException:
				Logger.error("[%s] Non existing item can not be deleted" % g.UUID)
				err = ERROR.NOT_EXISTING_ITEM_CAN_NOT_BE_DELETED
				break
			except SubscriptionNotFoundException:
				Logger.error("[%s] Subscription is not valid" % g.UUID)
				err = ERROR.SUBSCRIPTION_NOT_FOUND
				break
			except QuantityNotAvailableException as qnae:
				Logger.error("[%s] Quantity is not available [%s]" % (g.UUID, str(qnae)))
				err = ERROR.PRODUCT_AVAILABILITY_CHANGED
				break
			except EmptyCartException:
				Logger.error("[%s] Cart has become empty" % g.UUID)
				cart.total_discount = 0.0
				cart.total_offer_price = 0.0
				cart.total_display_price = 0.0
				cart.total_shipping_charges = 0.0
				cart.promo_codes = None
				self.is_cart_empty = True
				err = ERROR.CART_EMPTY
				break
			except Exception as e:
				Logger.error("[%s] Exception occurred in updating cart items [%s]" % (g.UUID, str(e)), exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break


			# 2 Payment Mode
			if data.get('payment_mode') is not None:
				cart.payment_mode = payment_modes_dict[data.get('payment_mode')]

			# 3 Coupon Update (Cart Level or Item level)
			if self.is_cart_empty == False:
				try:
					if 'promo_codes' in data and data['promo_codes'] != []:
						cart.promo_codes = map(str, data.get('promo_codes'))
					self.check_for_coupons_applicable(data)
				except CouponInvalidException as cie:
					Logger.error('[%s] Coupon can not be applied [%s]' % (g.UUID, str(cie)), exc_info=True)
					err = ERROR.COUPON_SERVICE_RETURNING_FAILURE_STATUS
					break

			# 4 Shipping address
			try:
				self.update_address(data, cart)
			except Exception as e:
				Logger.error('[%s] Shipping address could not be updated [%s]' % (g.UUID, str(e)), exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break


			# 5 update cart price
			try:
				self.update_cart_total_amounts(cart)
			except Exception as e:
				Logger.error('[%s] Shipping address could not be updated [%s]' % (g.UUID, str(e)), exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break
			# Selected Freebie
			try:
				if data.get('selected_freebee_code') is not None:
					cart.selected_freebee_items = json.dumps(data.get('selected_freebee_code'))
			except Exception as e:
				Logger.error('[%s] Selected Freebee code could not be set in cart [%s]' % (g.UUID, str(e)),
							 exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			# 6 Save cart
			try:
				db.session.add(cart)
				for each_cart_item in self.item_id_to_existing_item_dict.values():
					db.session.add(each_cart_item)
				if self.deleted_cart_items.values().__len__() > 0:
					for each_deleted_item in self.deleted_cart_items.values():
						db.session.delete(each_deleted_item)

			except Exception as e:
				Logger.error('[%s] Shipping address could not be updated [%s]' % (g.UUID, str(e)), exc_info=True)
				err = ERROR.DATABASE_ERROR
				break

			# 7 Create Response
			try:
				response_data = self.generate_response(None, cart)
			except Exception as e:
				Logger.error(
					'[%s] Exception occurred in creating response while updating the cart [%s]' % (g.UUID, str(e)),
					exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			error = False
			break;
		if error:
			db.session.rollback()
			return create_error_response(err)
		else:
			db.session.commit()
			return create_data_response(data=response_data)

	def create_cart(self, data):
		error = True
		err = None
		while True:

			# 0. Validation
			try:
				self.validate_create_new_cart(data)
			except EmptyCartException as ece:
				Logger.error(
					'[%s] Cart can not be created without an item [%s]' % (g.UUID, str(ece)),
					exc_info=True)
				err = ERROR.CART_EMPTY
				break
			except RequiredFieldMissing as rfm:
				Logger.error(
					'[%s] Required field is missing in creating cart API call[%s]' % (g.UUID, str(rfm)),
					exc_info=True)
				err = ERROR.CART_ITEM_MISSING
				break
			except IncorrectDataException as ide:
				Logger.error('[%s] Zero quantity can not be added[%s]' % (g.UUID, str(ide)),
							 exc_info=True)
				err = ERROR.INCORRECT_DATA
				break


			# 1. Initialize cart object
			try:
				self.cart_reference_uuid = uuid.uuid1().hex
				cart = Cart()
				self.populate_cart_object(data, cart)
			except Exception as e:
				Logger.error("[%s] Exception occurred in populating cart object [%s]" % (g.UUID, str(e)), exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break


			# 2. Calculate item prices and cart total
			try:
				self.get_price_and_update_in_cart_item(data)

			except SubscriptionNotFoundException as snfe:
				Logger.error("[%s] Subscript not found for data  [%s] [%s]" % (g.UUID, str(snfe)))
				err = ERROR.SUBSCRIPTION_NOT_FOUND
				break
			except QuantityNotAvailableException as qnae:
				Logger.error("[%s] Quantity is not available [%s]" % (g.UUID, str(qnae)))
				err = ERROR.PRODUCT_AVAILABILITY_CHANGED
				break
			except Exception as e:
				Logger.error("[%s] Exception occurred in getting price and update in cart item [%s]" % (g.UUID, str(e)),
							 exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break


			# 3. check coupons
			try:
				response_data = self.get_response_from_check_coupons_api(self.cart_items, data)
				self.update_discounts_item_level(response_data, self.cart_items)
			except CouponInvalidException as cie:
				Logger.error("[%s] Exception occurred in checking coupons for cart item [%s]" % (g.UUID, str(cie)))
				err = ERROR.COUPON_SERVICE_RETURNING_FAILURE_STATUS
				break
			except Exception as e:
				Logger.error("[%s] Exception occurred in checking coupons for cart item [%s]" % (g.UUID, str(e)))
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			# 4. apply shipping charges
			try:
				self.total_shipping_charges = get_shipping_charges(self.total_price, self.total_discount)
			except Exception as e:
				Logger.error(
					"[%s] Exception occurred in getting shipping charges for cart item [%s]" % (g.UUID, str(e)),
					exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			# 5. save in DB
			try:
				self.save_cart(data, cart)
			except Exception as e:
				Logger.error("[%s] Exception occurred in saving cart item in DB [%s]" % (g.UUID, str(e)), exc_info=True)
				ERROR.DATABASE_ERROR.message = str(e)
				err = ERROR.DATABASE_ERROR
				break

			# 6. create response
			try:
				response_data = self.generate_response(self.cart_items, cart)
			except Exception as e:
				Logger.error("[%s] Exception occurred in generating response for cart [%s]" % (g.UUID, str(e)),
							 exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			error = False
			break

		if error:
			db.session.rollback()
			return create_error_response(err)
		else:
			db.session.commit()
			return create_data_response(data=response_data)

	def save_cart(self, data, cart):
		cart.total_offer_price = self.total_price
		cart.total_display_price = self.total_display_price
		cart.total_discount = self.total_discount
		cart.total_shipping_charges = self.total_shipping_charges

		self.shipping_address = data.get('shipping_address')
		if self.shipping_address is not None:
			address = Address.get_address(self.shipping_address['name'], self.shipping_address['mobile'],
										  self.shipping_address['address'], self.shipping_address.get('city'),
										  self.shipping_address.get('pincode'), self.shipping_address.get('state'),
										  self.shipping_address.get('email'), self.shipping_address.get('landmark'))
			cart.shipping_address_ref = address.address_hash

		db.session.add(cart)

		for cart_item in self.cart_items:
			db.session.add(cart_item)

	def remove_cart_item_from_cart(self, cart_item_db):
		db.session.delete()

	def change_quantity_of_cart_item(self, cart_item_db, check_price_json, item):
		cart_item_db.quantity = item['quantity']
		cart_item_db.display_price = check_price_json['display_price']
		cart_item_db.offer_price = check_price_json['offer_price']

	def add_new_item_to_cart(self, cart_item_db, json_order_item, item):
		cart_item_db.cart_item_id = item['item_uuid']
		cart_item_db.cart_id = self.cart_reference_uuid
		cart_item_db.quantity = item['quantity']
		cart_item_db.cart_id = self.cart_reference_uuid
		cart_item_db.display_price = float(json_order_item['display_price'])
		cart_item_db.offer_price = float(json_order_item['offer_price'])

	def populate_cart_object(self, data, cart):

		cart.geo_id = int(data['geo_id'])
		cart.user_id = data['user_id']
		cart.cart_reference_uuid = self.cart_reference_uuid
		cart.order_type = order_types[0]
		if data.get('order_type') is not None:
			cart.order_type = order_types[data.get('order_type')]
		cart.order_source_reference = data['order_source_reference']
		if 'promo_codes' in data and data.__getitem__('promo_codes').__len__() != 0:
			cart.promo_codes = data.get('promo_codes')
		if data.get('payment_mode') is not None:
			cart.payment_mode = payment_modes_dict[data.get('payment_mode')]
		if data.get('selected_freebee_code') is not None:
			cart.selected_freebee_items = data.get('selected_freebee_code')

	def validate_create_new_cart(self, data):
		if 'orderitems' not in data or ('orderitems' in data and data['orderitems'].__len__() == 0):
			raise EmptyCartException(ERROR.CART_EMPTY)
		else:
			for each_cart_item in data['orderitems']:
				if each_cart_item['quantity'] == 0:
					raise IncorrectDataException(ERROR.CART_ZERO_QUANTITY_CAN_NOT_BE_ADDED)

	def fetch_items_price_return_dict(self, data):
		response_product_fetch_data = self.fetch_product_price(data['orderitems'], data)

		if response_product_fetch_data is None or response_product_fetch_data.__len__() == 0:
			raise SubscriptionNotFoundException(ERROR.SUBSCRIPTION_NOT_FOUND)

		order_item_dict = {}
		for response in response_product_fetch_data[0].get('items')[0].get('items'):
			order_item_dict[response.get('id')] = response
		return order_item_dict

	def fetch_product_price(self, items, data):
		request_items_ids = list()
		for item in items:
			request_items_ids.append(int(item["item_uuid"]))

		order_type = order_types[0]
		if data.get('order_type') is not None:
			order_type = order_types[data.get('order_type')]

		req_data = {
			"query": {
				"type": [order_type],
				"filters": {
					"id": request_items_ids
				},
				"select": config.SEARCH_API_SELECT_CLAUSE
			},
			"count": request_items_ids.__len__(),
			"offset": 0
		}

		return self.call_calculate_price_api(req_data)

	def call_calculate_price_api(self, req_data):

		request_data = json.dumps(req_data)
		Logger.info("[%s] Request data for calculate price API is [%s]" % (g.UUID, request_data))
		response = requests.post(url=current_app.config['PRODUCT_CATALOGUE_URL'], data=request_data,
								 headers={'Content-type': 'application/json'})
		json_data = json.loads(response.text)
		Logger.info("[%s] Response got from calculate Price API is [%s]" % (g.UUID, json.dumps(json_data)))
		if 'status' in json_data and json_data.get('status') != 200:
			ERROR.INTERNAL_ERROR.message = json_data['msg']
			raise Exception(ERROR.INTERNAL_ERROR)
		return json_data['results']

	def generate_response(self, new_items, cart):
		response_json = {
			"orderitems": [],
			"total_offer_price": self.total_price,
			"total_display_price": self.total_display_price,
			"total_discount": self.total_discount,
			"total_shipping_charges": self.total_shipping_charges,
			"cart_reference_uuid": cart.cart_reference_uuid,
			"benefits": self.benefits,
			"cart_items_count": self.get_count_of_items(new_items),
		}
		if self.shipping_address is not None:
			response_json['shipping_address'] = self.shipping_address

		if new_items is not None:
			items = list()
			for item in new_items:
				order_item_dict = {}
				order_item_dict["item_uuid"] = item.cart_item_id
				order_item_dict["display_price"] = item.display_price
				order_item_dict["offer_price"] = item.offer_price
				order_item_dict["quantity"] = item.quantity
				order_item_dict["item_discount"] = item.item_discount
				order_item_dict["title"] = item.title
				items.append(order_item_dict)
			response_json["orderitems"].append(items)

		elif self.item_id_to_existing_item_dict.values().__len__() != 0:
			items = list()
			for item in self.item_id_to_existing_item_dict.values():
				order_item_dict = {}
				order_item_dict["item_uuid"] = item.cart_item_id
				order_item_dict["display_price"] = str(item.display_price)
				order_item_dict["offer_price"] = str(item.offer_price)
				order_item_dict["quantity"] = item.quantity
				order_item_dict["item_discount"] = str(item.item_discount)
				order_item_dict["title"] = item.title
				items.append(order_item_dict)
			response_json["orderitems"].append(items)

		return response_json

	def update_discounts_item_level(self, response_data, cart_items):
		item_discount_dict = {}
		if response_data['success']:
			self.total_discount = float(response_data['totalDiscount'])
			self.benefits = response_data['benefits']
			for item in response_data['products']:
				item_discount_dict[item['itemid']] = item

			for each_cart_item in cart_items:
				each_cart_item.item_discount = float(item_discount_dict[str(each_cart_item.cart_item_id)]['discount'])
		else:
			error_msg = response_data['error'].get('error')
			ERROR.COUPON_SERVICE_RETURNING_FAILURE_STATUS.message = error_msg
			raise CouponInvalidException(ERROR.COUPON_SERVICE_RETURNING_FAILURE_STATUS)

	def update_cart_total_amounts(self, cart):
		cart.total_display_price = 0.0
		cart.total_offer_price = 0.0
		cart.total_discount = 0.0
		for each_cart_item in self.item_id_to_existing_item_dict.values():
			unit_offer_price = each_cart_item.offer_price
			unit_display_price = each_cart_item.display_price
			quantity = each_cart_item.quantity
			item_level_discount = each_cart_item.item_discount
			cart.total_display_price += (float(unit_display_price) * quantity)
			cart.total_offer_price += (float(unit_offer_price) * quantity)
			if item_level_discount is None:
				item_level_discount = 0.0
			cart.total_discount = float(cart.total_discount) + float(item_level_discount)

		self.total_display_price = cart.total_display_price
		self.total_price = cart.total_offer_price
		self.total_discount = cart.total_discount

		self.total_shipping_charges = get_shipping_charges(self.total_price, self.total_discount)
		cart.total_shipping_charges = self.total_shipping_charges

	def get_response_from_check_coupons_api(self, cart_items, data):
		url=current_app.config['COUPON_CHECK_URL']
		req_data = {
			"area_id": str(data['geo_id']),
			"customer_id": data['user_id'],
			'channel': data['order_source_reference'],
			"products": [
				{"item_id": str(each_cart_item.cart_item_id), "quantity": each_cart_item.quantity,
				 "coupon_code": each_cart_item.promo_codes}
				for each_cart_item in cart_items]
		}
		if 'payment_mode' in data :
			req_data['payment_mode'] = payment_modes_dict[data.get('payment_mode')]
			url+config.COUPON_QUERY_PARAM
		if 'promo_codes' in data and hasattr(data.get('promo_codes'), '__iter__') and data.get('promo_codes') != []:
			coupon_codes = map(str, data.get('promo_codes'))
			req_data["coupon_codes"] = coupon_codes

		header = {
			'X-API-USER': current_app.config['X_API_USER'],
			'X-API-TOKEN': current_app.config['X_API_TOKEN'],
			'Content-type': 'application/json'
		}

		response = requests.post(url=url, data=json.dumps(req_data),
								 headers=header)
		json_data = json.loads(response.text)
		Logger.info(
			"[%s] Request to check Coupon data passed is: [%s] and response is: [%s]" % (
			g.UUID, json.dumps(req_data), json_data))
		return json_data

	def get_price_and_update_in_cart_item(self, data):
		order_item_dict = self.fetch_items_price_return_dict(data)
		cart_item_list = list()
		for item in data['orderitems']:
			item_id = int(item['item_uuid'])
			json_order_item = order_item_dict.get(item_id)
			check_if_calculate_price_api_response_is_correct_or_quantity_is_available(item, json_order_item)
			cart_item = CartItem()
			cart_item.cart_item_id = item_id
			cart_item.cart_id = self.cart_reference_uuid
			cart_item.quantity = item['quantity']
			cart_item.display_price = float(json_order_item['basePrice'])
			cart_item.offer_price = float(json_order_item['offerPrice'])
			cart_item.promo_codes = item.get('promocodes')
			cart_item.same_day_delivery = 'SDD' if json_order_item.get('deliveryDays') == 0 else 'NDD'
			cart_item.transfer_price = float(json_order_item['offerPrice'])
			cart_item.title = json_order_item['title']
			cart_item_list.append(cart_item)

			self.total_price += float(json_order_item['offerPrice']) * int(item['quantity'])
			self.total_display_price += float(json_order_item['basePrice']) * int(item['quantity'])

		self.cart_items = cart_item_list

	def save_address_and_get_hash(self, data):
		addr1 = data.get('shipping_address')
		self.shipping_address = data.get('shipping_address')
		address = Address.get_address(name=addr1["name"], mobile=addr1["mobile"], address=addr1["address"],
									  city=addr1["city"], pincode=addr1["pincode"], state=addr1["state"],
									  email=addr1.get('email'), landmark=addr1.get('landmark'))

		return address

	def check_prices_of_item(self, request_items, data):

		response_data = self.fetch_product_price(request_items, data)
		if response_data is None or response_data.__len__() == 0:
			raise SubscriptionNotFoundException(ERROR.SUBSCRIPTION_NOT_FOUND)
		order_item_price_dict = {}

		for response in response_data[0].get('items')[0].get('items'):
			order_item_price_dict[response.get('id')] = response
		for each_item in request_items:
			check_if_calculate_price_api_response_is_correct_or_quantity_is_available(each_item, order_item_price_dict[int(each_item['item_uuid'])])

		return order_item_price_dict

	def update_cart_items(self, data, cart):

		self.item_id_to_existing_item_dict = {}
		for existing_cart_item in cart.cartItem:
			self.item_id_to_existing_item_dict[existing_cart_item.cart_item_id] = existing_cart_item

		no_of_left_items_in_cart = self.item_id_to_existing_item_dict.values().__len__()
		self.deleted_cart_items = {}
		updated_cart_items = {}
		newly_added_cart_items = {}
		if 'orderitems' in data and data['orderitems'].__len__() > 0:

			for data_item in data['orderitems']:

				if data_item['quantity'] == 0 and no_of_left_items_in_cart > 0:
					existing_cart_item = self.item_id_to_existing_item_dict.get(data_item['item_uuid'])
					if existing_cart_item is None:
						raise IncorrectDataException(ERROR.NOT_EXISTING_ITEM_CAN_NOT_BE_DELETED)
					del self.item_id_to_existing_item_dict[data_item['item_uuid']]
					no_of_left_items_in_cart = self.item_id_to_existing_item_dict.values().__len__()
					self.deleted_cart_items[data_item['item_uuid']] = existing_cart_item

				elif data_item['item_uuid'] in self.item_id_to_existing_item_dict:
					existing_cart_item = self.item_id_to_existing_item_dict.get(data_item['item_uuid'])
					existing_cart_item.quantity = data_item['quantity']
					existing_cart_item.promo_codes = data_item.get('promo_codes')
					# updated_cart_items[data_item['item_uuid']] = existing_cart_item
				elif data_item['item_uuid'] not in self.item_id_to_existing_item_dict and data_item['quantity'] > 0:
					new_cart_item = CartItem()
					new_cart_item.cart_id = cart.cart_reference_uuid
					new_cart_item.cart_item_id = data_item['item_uuid']
					new_cart_item.quantity = data_item['quantity']
					new_cart_item.promo_codes = data_item.get('promo_codes')
					new_cart_item.item_discount = 0.0
					# newly_added_cart_items[data_item['item_uuid']] = new_cart_item
					self.item_id_to_existing_item_dict[int(data_item['item_uuid'])] = new_cart_item
					no_of_left_items_in_cart = self.item_id_to_existing_item_dict.values().__len__()

				if data_item['quantity'] == 0 and no_of_left_items_in_cart == 0:
					Logger.info("[%s] Cart is empty" % g.UUID)
					raise EmptyCartException(ERROR.CART_EMPTY)

		request_items = list()
		for cart_item in self.item_id_to_existing_item_dict.values():
			request_item_detail = {"item_uuid": cart_item.cart_item_id, "quantity": cart_item.quantity}
			request_items.append(request_item_detail)

		if self.item_id_to_existing_item_dict.values().__len__() > 0:
			order_item_price_dict = self.check_prices_of_item(request_items, data)
			Logger.info("order_item_price_dict is [%s]" % (json.dumps(order_item_price_dict)))
			for key in self.item_id_to_existing_item_dict:
				existing_cart_item = self.item_id_to_existing_item_dict[key]
				key = int(key)
				cart_item = order_item_price_dict.get(key)
				if cart_item is not None:
					existing_cart_item.same_day_delivery = 'SDD' if cart_item.get('deliveryDays') == 0 else 'NDD'
					existing_cart_item.display_price = cart_item.get('basePrice')
					existing_cart_item.offer_price = cart_item.get('offerPrice')
					existing_cart_item.transfer_price = cart_item.get('transferPrice')
					existing_cart_item.title = cart_item.get('title')

	def check_for_coupons_applicable(self, data):
		response_data = self.get_response_from_check_coupons_api(self.item_id_to_existing_item_dict.values(), data)
		self.update_discounts_item_level(response_data, self.item_id_to_existing_item_dict.values())

	def update_address(self, data, cart):
		if data.get('shipping_address') is not None:
			address = self.save_address_and_get_hash(data)
			cart.shipping_address_ref = address.address_hash
		elif cart.shipping_address_ref is not None:
			shipping_address = Address.query.filter_by(address_hash = cart.shipping_address_ref).first()
			self.shipping_address = self.create_address_json(shipping_address)

	def remove_cart(self, cart_reference_id):
		if cart_reference_id is None:
			ERROR.INTERNAL_ERROR.message = "Cart reference id can not be Null"
			raise Exception(ERROR.INTERNAL_ERROR)
		db.session.query(CartItem).filter(CartItem.cart_id == cart_reference_id).delete()
		db.session.query(OrderShipmentDetail).filter(OrderShipmentDetail.cart_id == cart_reference_id).delete()
		db.session.query(Cart).filter(Cart.cart_reference_uuid == cart_reference_id).delete()



	def get_count_of_items(self, new_items):
		if new_items is not None:
			return new_items.__len__()
		else:
			return self.item_id_to_existing_item_dict.values().__len__()

	def add_item_to_cart(self, body):
		try:
			request_data = parse_request_data(body)
			validate(request_data, CREATE_CART_SCHEMA)
			cart = self.get_cart_for_geo_user_id(request_data['data'])
			if cart is not None:
				return self.add_item_to_existing_cart_no_price_cal(cart, request_data['data'])
			else:
				return self.create_cart_no_price_cal(request_data['data'])
		except IncorrectDataException as ide:
			Logger.error("[%s] Validation Error [%s]" % (g.UUID, str(ide.message)))
			return create_error_response(ide)
		except Exception as e:
			Logger.error('[%s] Exception occured while creating/updating cart [%s]' % (g.UUID, str(e)), exc_info=True)
			ERROR.INTERNAL_ERROR.message = str(e)
			return create_error_response(ERROR.INTERNAL_ERROR)

	def create_cart_no_price_cal(self, data):
		error = True
		err = None
		while True:

			# 0. Validation
			try:
				self.validate_create_new_cart(data)
			except RequiredFieldMissing as rfm:
				Logger.error(
					'[%s] Required field is missing in creating cart API call[%s]' % (g.UUID, str(rfm)),
					exc_info=True)
				err = ERROR.CART_ITEM_MISSING
				break
			except IncorrectDataException as ide:
				Logger.error('[%s] Zero quantity can not be added[%s]' % (g.UUID, str(ide)),
							 exc_info=True)
				err = ERROR.INCORRECT_DATA
				break


			# 1. Initialize cart object
			try:
				self.cart_reference_uuid = uuid.uuid1().hex
				cart = Cart()
				self.prepare_cart_object(data, cart)
			except Exception as e:
				Logger.error("[%s] Exception occurred in populating cart object [%s]" % (g.UUID, str(e)), exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break


			# 2. save in DB
			try:
				self.save_new_item_to_cart(cart)
			except Exception as e:
				Logger.error("[%s] Exception occurred in saving cart item in DB [%s]" % (g.UUID, str(e)), exc_info=True)
				ERROR.DATABASE_ERROR.message = str(e)
				err = ERROR.DATABASE_ERROR
				break

			# 3. create response
			try:
				response_data = self.generate_add_item_to_cart_response(self.cart_items, cart)
			except Exception as e:
				Logger.error("[%s] Exception occurred in generating response for cart [%s]" % (g.UUID, str(e)),
							 exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			error = False
			break

		if error:
			db.session.rollback()
			return create_error_response(err)
		else:
			db.session.commit()
			return create_data_response(data=response_data)

	def prepare_cart_object(self, data, cart):

		cart.geo_id = int(data['geo_id'])
		cart.user_id = data['user_id']
		cart.cart_reference_uuid = self.cart_reference_uuid
		cart.order_type = order_types[0]
		if data.get('order_type') is not None:
			cart.order_type = order_types[data.get('order_type')]
		cart.order_source_reference = data['order_source_reference']
		cart_item_list = list()
		for item in data['orderitems']:
			cart_item = CartItem()
			cart_item.cart_item_id = item['item_uuid']
			cart_item.cart_id = self.cart_reference_uuid
			cart_item.quantity = 1 if item.get('quantity') is None else item.get('quantity')
			cart_item_list.append(cart_item)

		self.cart_items = cart_item_list

	def save_new_item_to_cart(self, cart):
		db.session.add(cart)
		for cart_item in self.cart_items:
			db.session.add(cart_item)

	def generate_add_item_to_cart_response(self, new_items, cart):
		response_json = {
			"cart_reference_uuid": cart.cart_reference_uuid,
			"cart_items_count": self.get_count_of_items(new_items)
		}
		return response_json

	def add_item_to_existing_cart_no_price_cal(self, cart, data):
		error = True
		err = None
		while True:
			# 1 Item update(Added, removed, update)
			try:
				self.update_cart_items_no_price_cal(cart, data)

			except IncorrectDataException:
				Logger.error("[%s] Non existing item can not be deleted" % g.UUID)
				err = ERROR.NOT_EXISTING_ITEM_CAN_NOT_BE_DELETED
				break
			except SubscriptionNotFoundException:
				Logger.error("[%s] Subscription is not valid" % g.UUID)
				err = ERROR.SUBSCRIPTION_NOT_FOUND
				break
			except EmptyCartException:
				Logger.error("[%s] Cart has become empty" % g.UUID)
				self.is_cart_empty = True
				err = ERROR.CART_EMPTY
				break
			except Exception as e:
				Logger.error("[%s] Exception occurred in updating cart items [%s]" % (g.UUID, str(e)), exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			# 6 Save cart
			try:

				for each_cart_item in self.item_id_to_existing_item_dict.values():
					db.session.add(each_cart_item)
				if self.deleted_cart_items.values().__len__() > 0:
					for each_deleted_item in self.deleted_cart_items.values():
						db.session.delete(each_deleted_item)

			except Exception as e:
				Logger.error('[%s] Shipping address could not be updated [%s]' % (g.UUID, str(e)), exc_info=True)
				err = ERROR.DATABASE_ERROR
				break

			# 7 Create Response
			try:
				response_data = self.generate_add_item_to_cart_response(self.item_id_to_existing_item_dict, cart)
			except Exception as e:
				Logger.error(
					'[%s] Exception occurred in creating response while updating the cart [%s]' % (g.UUID, str(e)),
					exc_info=True)
				ERROR.INTERNAL_ERROR.message = str(e)
				err = ERROR.INTERNAL_ERROR
				break

			error = False
			break;
		if error:
			db.session.rollback()
			return create_error_response(err)
		else:
			db.session.commit()
			return create_data_response(data=response_data)

	def update_cart_items_no_price_cal(self, cart, data):
		self.item_id_to_existing_item_dict = {}
		for existing_cart_item in cart.cartItem:
			self.item_id_to_existing_item_dict[existing_cart_item.cart_item_id] = existing_cart_item

		no_of_left_items_in_cart = self.item_id_to_existing_item_dict.values().__len__()
		self.deleted_cart_items = {}

		if 'orderitems' in data and data['orderitems'].__len__() > 0:

			for data_item in data['orderitems']:

				if data_item['quantity'] == 0 and no_of_left_items_in_cart > 0:
					existing_cart_item = self.item_id_to_existing_item_dict.get(data_item['item_uuid'])
					if existing_cart_item is None:
						raise IncorrectDataException(ERROR.NOT_EXISTING_ITEM_CAN_NOT_BE_DELETED)
					del self.item_id_to_existing_item_dict[data_item['item_uuid']]
					no_of_left_items_in_cart = self.item_id_to_existing_item_dict.values().__len__()
					self.deleted_cart_items[data_item['item_uuid']] = existing_cart_item

				elif data_item['item_uuid'] in self.item_id_to_existing_item_dict:
					existing_cart_item = self.item_id_to_existing_item_dict.get(data_item['item_uuid'])
					existing_cart_item.quantity = existing_cart_item + 1 if data_item.get(
						'quantity') is None else data_item.get('quantity')

				elif data_item['item_uuid'] not in self.item_id_to_existing_item_dict and data_item['quantity'] > 0:
					new_cart_item = CartItem()
					new_cart_item.cart_id = cart.cart_reference_uuid
					new_cart_item.cart_item_id = data_item['item_uuid']
					new_cart_item.quantity = 1 if data_item.get('quantity') is None else data_item.get('quantity')
					self.item_id_to_existing_item_dict[int(data_item['item_uuid'])] = new_cart_item
					no_of_left_items_in_cart = self.item_id_to_existing_item_dict.values().__len__()

				if data_item['quantity'] == 0 and no_of_left_items_in_cart == 0:
					Logger.info("[%s] Cart is empty" % g.UUID)
					raise EmptyCartException(ERROR.CART_EMPTY)

	def create_address_json(self, shipping_address):
		shipping_add = {}
		shipping_add["name"] = shipping_address.name
		shipping_add["mobile"] = shipping_address.mobile
		shipping_add["address"] = shipping_address.address
		shipping_add["city"] = shipping_address.city
		shipping_add["pincode"] = shipping_address.pincode
		shipping_add["state"] = shipping_address.state
		shipping_add["email"] = shipping_address.email
		shipping_add["landmark"] = shipping_address.landmark
		return shipping_add
