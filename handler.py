import json
import os
from datetime import date, datetime
import decimal
import logging

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
        logger.debug('event: (%s): %s', type(event), event)
    # Support for serverless -local testing
    if "resource" in event:
        # AWS API Gateway Lambda Proxy
        try:
            input = json.loads(event['body'])
            msgSig = event['headers']['X-Webhook-Signature']
        except Exception as e:
            logger.exception("Error parsing event: %s", e)
            return(400, "Error parsing event")
    else:
        # Support for serverless invoke local --function functionName
        # (running code locally by emulating the AWS Lambda environment)
        input = event
        msgSig = "TEST"
    if config.DEBUG > 4:
        logger.debug('input: (%s): %s', type(input), json.dumps(input))

    # Call the core business logic entry function
    response = eventManager(input, msgSig)

    if config.DEBUG:
        logger.debug(json.dumps(response, default=json_serial))
    return response
