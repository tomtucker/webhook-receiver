import hmac, hashlib, json, base64
import os
from datetime import date, datetime
import decimal
import logging
import hmac

import config 
from utils import setup_custom_logger, api_return, json_serial
from eventManager import eventManager

def vinEvent(event, context):
    """CashBox Proxy Service AWS Lambda handler function

    Arguments:
        event {dict} -- AWS Lambda uses this parameter to pass in event data to the handler.  This parameter is usually of the Python dict type. It can also be list, str, int, float, or NoneType type.
        context {LambdaContext} -- AWS Lambda uses this parameter to provide runtime information to handler.

    Returns:
        json -- JSON response in format required b API Gateway
    """
    logger = logging.getLogger('root')

    if config.DEBUG > 3:
        logger.debug('raw event: (%s): %s', type(event), event)

    # Support for serverless -local testing
    if "headers" not in event:
        # Support for serverless invoke local --function <functionName> -p <path to JSON input data>
        # (running code locally by "emulating" the AWS Lambda environment)
        new_event = {
            'headers': {
                "X-Webhook-Signature": base64.b64encode(
                    hmac.new(
                        config.HMAC_KEY.encode('utf-8'),
                        json.dumps(event, separators=(',', ':')).encode('utf-8'),
                        hashlib.sha256
                    ).digest()
                ).decode('utf-8')
            },
            'body': json.dumps(event, separators=(',', ':')).encode('utf-8').decode('utf-8')
        }
        event = new_event
        logger.warn("Local mode detected")
    if config.DEBUG > 3:
        logger.debug('event: (%s): %s', type(event), event)

    # Call the core business logic entry function
    response = eventManager(event)
    logger.debug(json.dumps(response, default=json_serial))
    return response
