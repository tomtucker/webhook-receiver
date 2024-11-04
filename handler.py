import hmac
import hashlib
import json
import base64

# import os
# from datetime import date, datetime
# import decimal
import logging

import config
from utils import api_return
from eventManager import event_manager


def vin_event(event, context):
    """Subscribe Proxy Service AWS Lambda handler function

    Arguments:
        event {dict} -- AWS Lambda uses this parameter to pass in event data
                         to the handler.  This parameter is usually of the
                         Python dict type. It can also be list, str, int,
                         float, or NoneType type.
        context {LambdaContext} -- AWS Lambda uses this parameter to provide
                                   runtime information to handler.

    Returns:
        json -- JSON response in format required b API Gateway
    """
    logger = logging.getLogger("root")

    if config.DEBUG > 3:
        logger.setLevel(config.DEBUG)
        logger.debug("raw event: (%s): %s", type(event), event)

    # Support for serverless -local testing
    # "headers" are the HTTP headers of the POST, not to be confused with
    # "header" which is part of POST body
    if "headers" not in event:
        # Support for
        #   serverless invoke local --function <functionName> -p <path to JSON input data>
        # (running code locally by "emulating" the AWS Lambda environment)
        try:
            message_id = event["header"]["message_id"]
        except (KeyError, TypeError):
            logger.error("Cannot set messageIid from header\n%s", event)
            return api_return(
                "406",
                return_string="ERROR: Cannot parse message header",
                event=event,
            )  # , request = f"{json.dumps(event, default=json_serial, separators=(',', ':'))})")

        logger.warning(
            "%s    Local mode detected. Computing signature for HTTP headers",
            message_id,
        )
        new_event = {
            "headers": {
                "X-Webhook-Signature": base64.b64encode(
                    hmac.new(
                        config.HMAC_KEY.encode("utf-8"),
                        json.dumps(event, separators=(",", ":")).encode(
                            "utf-8"
                        ),
                        hashlib.sha256,
                    ).digest()
                ).decode("utf-8")
            },
            "body": json.dumps(event, separators=(",", ":"))
            .encode("utf-8")
            .decode("utf-8"),
        }
        event = new_event
        logger.info(
            "Running in local mode with computed signature (%s)",
            event["headers"],
        )

    # Call the core business logic entry function
    response = event_manager(event)
    # logger.debug(json.dumps(response, default=json_serial))
    return response
