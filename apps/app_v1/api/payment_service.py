import json
from utils.jsonutils.json_utility import JsonUtility
import logging
from utils.jsonutils.output_formatter import create_error_response, create_data_response
from apps.app_v1.models.models import MasterOrder, Address, Payment, db
import requests
from flask import g, current_app
from config import APP_NAME
from apps.app_v1.api import ERROR

__author__ = 'amit.bansal'

Logger = logging.getLogger(APP_NAME)


class PaymentInfo(JsonUtility):

    def save_payment_details(self, pure_json, order_id):
        payment_objs = list()
        if "childTxns" in pure_json:
            for childTxn in pure_json["childTxns"]:
                payment_data = Payment()
                payment_data.order_id = order_id
                payment_data.payment_gateway = childTxn.get('bankGateway', None)
                payment_data.payment_method = childTxn.get('paymentMode', None)
                payment_data.pg_txn_id = childTxn.get('pgTxnId', None)
                payment_data.txn_date = childTxn.get('txnDate', None)
                payment_data.txn_amt = childTxn.get('txnAmount', 0.0)
                payment_data.bank_txn_id = childTxn.get('bankTxnId', None)
                payment_data.status = childTxn.get('status', 'pending')
                payment_objs.append(payment_data)
        else:
            payment_data = Payment()
            payment_data.order_id = order_id
            payment_data.payment_gateway = pure_json.get('bankGateway', None)
            payment_data.payment_method = pure_json.get('paymentMode', None)
            payment_data.pg_txn_id = pure_json.get('pgTxnId', None)
            payment_data.txn_date = pure_json.get('txnDate', None)
            payment_data.txn_amt = pure_json.get('txnAmount', 0.0)
            payment_data.bank_txn_id = pure_json.get('bankTxnId', None)
            payment_data.status = pure_json.get('status', 'pending')
            payment_objs.append(payment_data)

        #save in DB
        for payment in payment_objs:
            db.session.add(payment)

        return payment_objs


    def get_order_prices(self, request):
        try:
            Logger.info("[%s]************************* Get Order Price Start **************************" %g.UUID)
            raw_data = request.data
            Logger.info('{%s} Data from request {%s}' % (g.UUID, raw_data))
            pure_json = json.loads(raw_data)

            if 'order_id' not in pure_json:
                ERROR.KEY_MISSING.message = 'key missing is order_id'
                return create_error_response(ERROR.KEY_MISSING)

            order_data = MasterOrder.get_order(pure_json['order_id'])
            if order_data is None:
                return create_error_response(ERROR.NO_ORDER_FOUND_ERROR)

            billing_address = Address.find(order_data.billing_address_ref)

            response = {}
            response['order_id'] = order_data.order_id
            response['total_offer_price'] = order_data.total_offer_price
            response['total_shipping_charges'] = order_data.total_shipping
            response['total_discount'] = order_data.total_discount
            response['total_payable_amount'] = order_data.total_payble_amount
            response['user_id'] = order_data.user_id
            response['address'] = billing_address.convert_to_json()
            Logger.info("[%s] Response for Get Order Price is: [%s]" %(g.UUID, json.dumps(response)))
            Logger.info("[%s]************************* Get Order Price End **************************" %g.UUID)
            return create_data_response(data=response)

        except Exception as e:
            Logger.error('{%s} Exception occured ' % g.UUID, exc_info=True)
            ERROR.INTERNAL_ERROR.message = str(e)
            return create_error_response(ERROR.INTERNAL_ERROR)

    def update_payment_details(self, request):
        Logger.info("[%s]************************* Update Payment Details Start **************************" %g.UUID)
        required_fields = ["order_id", "status"]
        required_fields_in_child_txn = ["paymentMode"]
        try:
            raw_data = request.data
            Logger.info('{%s} Data from request {%s}' % (g.UUID, raw_data))
            pure_json = json.loads(raw_data)

            for field in required_fields:
                    if field not in pure_json:
                        ERROR.KEY_MISSING.message = 'key missing is %s' % field
                        return create_error_response(ERROR.KEY_MISSING)

            order_data = MasterOrder.get_order(pure_json['order_id'])
            if order_data is None:
                return create_error_response(ERROR.NO_ORDER_FOUND_ERROR)

            if order_data.payment_status != "pending":
                 return create_data_response(data={"message" : "payment is already updated"})

            #update payment_status in order table
            order_data.payment_status = pure_json['status']
            db.session.add(order_data)

            if "childTxns" in pure_json:
                for child in pure_json["childTxns"]:
                    for field in required_fields_in_child_txn:
                        if field not in child:
                            ERROR.KEY_MISSING.message = 'key missing in childTxns is %s' % field
                            return create_error_response(ERROR.KEY_MISSING)

            payment_objs = self.save_payment_details(pure_json, pure_json['order_id'])

            #update payment and send order to OPS-Panel
            response = None
            """
            ops_panel_request = PushToOpsPanel(order_id=pure_json['order_id'], payments=payment_objs)
            Logger.info('{%s} updating payment status for order : {%s} '%(g.UUID, pure_json['order_id']))
            ops_panel_request.update_payment(pure_json)

            response_text = ops_panel_request.get_response().text
            Logger.info('{%s} response text for update order {%s}'%(g.UUID, response_text))
            response = json.loads(response_text)
            if str(response['status']).lower() == 'success':
                response_obj = response
            else:
                Logger.error('{%s} Order updation failed for order {%s} '%(g.UUID, pure_json['order_id']), exc_info=True)
                raise Exception(str(response['message']))

            response = response_obj
            """
            #create response data here
            db.session.commit()
            Logger.info("[%s]************************* Update Payment Details End **************************" %g.UUID)
            Logger.info("[%s] Response for Update Payment Detail API is: [%s]" %(g.UUID, json.dumps(response)))
            return create_data_response(data=response)

        except Exception as e:
            db.session.rollback()
            Logger.error('{%s} Exception occured ' % g.UUID, exc_info=True)
            ERROR.INTERNAL_ERROR.message=e.message
            return create_error_response(ERROR.INTERNAL_ERROR)


    def get_payment_details(self, request):
        try:
            Logger.info("[%s]************************* Get Payment Details Start **************************" %g.UUID)
            raw_data = request.data
            Logger.info('{%s} Data from request {%s}' % (g.UUID, raw_data))
            pure_json = json.loads(raw_data)

            if 'order_id' not in pure_json:
                ERROR.KEY_MISSING.message = 'key missing is order_id'
                return create_error_response(ERROR.KEY_MISSING)

            order_data = MasterOrder.get_order(pure_json['order_id'])

            if order_data is None:
                return create_error_response(ERROR.NO_ORDER_FOUND_ERROR)

            payments = Payment.get_payment_details(pure_json['order_id'])

            if len(payments) == 0:
                #call to payment service api
                url = current_app.config['PAYMENT_SERVICE_URL']
                data = {}
                data['order_id'] = pure_json['order_id']
                data['update_order_service'] = False
                headers = {"Content-type": "application/json"}
                if  current_app.config.get("PAYMENT_AUTH_KEY"):
                    headers['Authorization'] = current_app.config.get("PAYMENT_AUTH_KEY")

                request = requests.post(url=url, data=json.dumps(data), headers=headers)
                if request.status_code == 200:
                     response = json.loads(request.text)
                     if response['status'] == "success":
                        #update payment_status in order table
                        order_data.payment_status = response['data']['status']
                        db.session.add(order_data)
                        payments = self.save_payment_details(response['data'], pure_json['order_id'])
                        db.session.commit()
                     else:
                        raise Exception(response['error']["message"])
                else:
                   raise Exception("could not get payment details")

            response = {}
            payment_details = list()
            for payment in payments:
                payment_data = {}
                payment_data['payment_gateway'] = payment.payment_gateway
                payment_data['payment_method'] = payment.payment_method
                payment_data['pg_txn_id'] = payment.pg_txn_id
                payment_data['txn_date'] = payment.txn_date
                payment_data['txn_amt'] = payment.txn_amt
                payment_data['bank_txn_id'] = payment.bank_txn_id
                payment_data['status'] = payment.status
                payment_details.append(payment_data)

            response['payment_details'] = payment_details
            response['payment_status'] = order_data.payment_status
            Logger.info("[%s]************************* Get Payment Details End **************************" %g.UUID)
            #Logger.info("[%s] Response for Get Payment Detail API is: [%s]" %(g.UUID, json.dumps(response)))
            return create_data_response(data=response)

        except Exception as e:
            Logger.error('{%s} Exception occured ' % g.UUID, exc_info=True)
            ERROR.INTERNAL_ERROR.message=e.message
            return create_error_response(ERROR.INTERNAL_ERROR)

