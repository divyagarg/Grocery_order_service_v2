__author__ = 'divyagarg'
from config import RESPONSE_JSON




def create_error_response(ERROR_DETAIL):
    settings = RESPONSE_JSON
    response_json = settings['RESPONSE_JSON'].copy()
    error_response = settings['ERROR_RESPONSE'].copy()

    error_response['code'] = ERROR_DETAIL.code
    error_response['message'] = ERROR_DETAIL.message

    response_json['status'] = False
    response_json['error'] = error_response

    return response_json


def create_data_response(data):
    settings = RESPONSE_JSON
    response_json = settings['RESPONSE_JSON'].copy()
    response_json['status'] = True
    response_json['data'] = data
    return response_json