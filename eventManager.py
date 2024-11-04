"""Process a Subscribe Push Message

This function is responsible for handling a Subscribe Push Notification
message. It performs the following tasks:

1. Parses the message header to extract relevant information such as the class
   name, event name, message ID, and event timestamp.
2. Validates the message signature to ensure the message is authentic.
3. Determines the appropriate class ID based on the class name and the message
   content.
4. Stores the message in the appropriate storage mechanism.
5. Handles specific logic for different message types, such as modifying an
   AutoBill, processing a successful or failed transaction, or handling
   entitlement and invoice messages.
6. Returns an API response with the appropriate status code and message.

Args:
    event (dict): A dictionary containing the Subscribe Push Notification
                  message and HTTP headers.

Returns:
    dict: An API response containing a status code and message.
"""

import json

# import boto3
# import os
import logging

# import datetime

import config

# import hmacValidation as auth
from utils import (
    api_return,
    validate,
    storeMessage,
    get_modification_tx,
    get_subscription,
)


def event_manager(event: dict):
    """eventManager Process a Subscribe Push Message

    Arguments:
        event {dict} -- dictionary containing a Subscribe Push Notification
                        message and HTTP Headers

    Returns:
        dict -- api_return containing a statusCode and message
    """
    logger = logging.getLogger("root")

    # Break down the message into useful components
    message = json.loads(event["body"])
    try:
        class_name = message["header"]["class_name"]
        event_name = message["header"]["event_name"]
        message_id = message["header"]["message_id"]
        event_timestamp = message["header"]["event_timestamp"]
        logger.info("%s %s/%s    Received", message_id, class_name, event_name)
    except KeyError as e:
        logger.exception(
            "Cannot parse message header    %s",
            json.dumps(event, separators=(",", ":")).encode("utf-8"),
        )
        return api_return(
            "406",
            message=f"{json.dumps(event, separators=(',', ':')).encode('utf-8')}",
            return_string=(
                f"ERROR: Cannot parse message header. Missing key: {str(e)}"
            ),
        )

    # authentication of message against received HMAC signature
    try:
        # logger.debug("Received signature: %s", msgSig)
        if validate(
            message_id, message, event["headers"]["X-Webhook-Signature"]
        ):
            pass
        else:
            logger.error(
                "%s %s/%s   Signatures do not match",
                message_id,
                class_name,
                event_name,
            )
            return api_return(
                "403",
                message_id=f"{message_id}",
                return_string="Signature does not match",
            )
    except KeyError as e:
        logger.error(
            "message_id: %s %s/%s    Signature Validation error: Missing key %s",
            message_id,
            class_name,
            event_name,
            str(e),
        )
        return api_return(
            "403",
            message_id=f"{message_id}",
            return_string="Signature error: Missing required data",
        )

    # These are the object IDs expected for each class_name
    # Note inconsistent case of 'merchantAutobillId' for entilement messages.
    # That's the way it is received
    classIds = {
        "accounts": "merchantAccountId",
        "adjustments": "merchantRefundId",
        "autobills": "merchantAutoBillId",
        "transactions": "merchantTransactionId",
        "entitlement": "merchantAccountId",
        "invoices": "invoice_id",
        "payment methods": "merchantPaymentMethodId",
    }

    # This loop sets the class_id for the object based on the class_name in
    # the messsage or uses 'VID' if the expected class_id is not found
    class_id = None
    value = None
    for key, value in classIds.items():
        if class_name == key:
            logger.debug(
                "%s  %s/%s. Looking for %s",
                message_id,
                class_name,
                event_name,
                value,
            )

            # DGD-1786: Handle KeyError for malformed objects missing Merchant
            # class identifiers
            if class_name == "autobills" and event_name == "modify":
                # Special handling for autobills/modify messages:
                # The message CONTAINS the object instead of IS the object
                try:
                    if message["content"]["autobill"]["merchantAutoBillId"]:
                        class_id = message["content"]["autobill"][
                            "merchantAutoBillId"
                        ]
                    else:
                        logger.warning(
                            "%s  %s/%s    Missing '%s' trying 'VID' instead",
                            message_id,
                            class_name,
                            event_name,
                            value,
                        )
                    break
                except KeyError as e:
                    logger.exception(
                        "%s %s/%s    Cannot set class ID: Missing key %s",
                        message_id,
                        class_name,
                        event_name,
                        str(e),
                    )
                    return api_return(
                        "400",
                        message_id=f"{message_id}",
                        return_string=(
                            f"Cannot set class id or vid: Missing key {str(e)}"
                        ),
                    )

            elif class_name == "accounts" and event_name == "data change":
                # Special handling for accounts/data change messages:
                # The message CONTAINS the object instead of IS the object
                try:
                    if message["content"]["account"]["merchantAccountId"]:
                        class_id = message["content"]["account"][
                            "merchantAccountId"
                        ]
                    else:
                        class_id = message["content"]["account"]["VID"]
                        logger.warning(
                            "%s %s/%s    Using 'VID' instead of %s",
                            message_id,
                            class_name,
                            event_name,
                            value,
                        )
                    break
                except KeyError as e:
                    logger.exception(
                        "%s  %s/%s        Cannot set class ID or vid: Missing key %s",
                        message_id,
                        class_name,
                        event_name,
                        str(e),
                    )
                    return api_return(
                        "400",
                        message_id=f"{message_id}",
                        return_string=(
                            f"Cannot set class ID or vid: Missing key {str(e)}"
                        ),
                    )
            elif class_name == "invoices":
                # Special handling for invoice messages:
                # The invoice identifier is in the header.
                try:
                    if message["header"]["invoice_id"]:
                        class_id = message["header"]["invoice_id"]
                    else:
                        class_id = message["content"]["VID"]
                        logger.warning(
                            "%s %s/%s Using 'VID' instead of %s",
                            message_id,
                            class_name,
                            event_name,
                            value,
                        )
                    break

                except KeyError as e:
                    logger.exception(
                        "%s %s/%s    Cannot set class ID: Missing key %s",
                        message_id,
                        class_name,
                        event_name,
                        str(e),
                    )
                    return api_return(
                        "400",
                        message_id=f"{message_id}",
                        return_string=(
                            f"Cannot set class ID: Missing key {str(e)}"
                        ),
                    )
            else:
                try:
                    if message["content"][value]:
                        class_id = message["content"][value]
                    else:
                        class_id = message["content"]["VID"]
                        logger.warning(
                            "%s %s/%s    Using 'VID' instead of %s",
                            message_id,
                            class_name,
                            event_name,
                            value,
                        )
                    break

                except KeyError as e:
                    logger.exception(
                        "%s %s/%s    Cannot set class ID: Missing key %s",
                        message_id,
                        class_name,
                        event_name,
                        str(e),
                    )
                    return api_return(
                        "400",
                        message_id=f"{message_id}",
                        return_string=(
                            f"Cannot set class ID for message: Missing key {str(e)}"
                        ),
                    )

    # Store the message
    if class_id is not None and value is not None:
        logger.info(
            "%s %s/%s    %s = >%s<",
            message_id,
            class_name,
            event_name,
            value,
            class_id,
        )
    response = storeMessage(class_id, message)

    if int(response["statusCode"]) > 299:
        # If unsuccessful storing original message, error details
        # logged and exit with API response set by storeMessage()
        return response

    if class_name == "accounts":
        # If accounts...No change to AutoBill status or billingState
        pass

    elif class_name == "adjustments":
        # If refund...No change to AutoBill status or billingState
        pass

    elif class_name == "autobills" and event_name == "modify":
        # For autobills/modify messages, fetch the modification Transaction, if
        # any, that resulted from the modfification. Modification Transactions
        # occur if there is a pro-rated charge triggered by the
        # AutoBill.modify() operation (adding a Product mid-billing cycle).
        #
        # TODO: Handle refunds triggered by AutoBill.modify()
        # return api_return("200", classIds[class_name][0]+":"+classIds[class_name][1])

        # Get the last modify transaction for this subscription
        transaction = get_modification_tx(
            message_id, message["content"]["autobill"], event_timestamp
        )
        if transaction is None or "merchantTransactionId" not in transaction:
            # No modification Transactions found
            logger.warning(
                "%s %s/%s    Modification Transaction not found",
                message_id,
                class_name,
                event_name,
            )
            return api_return(
                "202",
                message_id=f"{message_id}",
                return_string="Modification Transaction not found",
            )
        if "return" in transaction:
            logger.warning(
                "%s %s/%s    get_modification_tx issue:\n%s",
                message_id,
                class_name,
                event_name,
                json.dumps(response, indent=4),
            )
            return api_return(
                "206",
                message_id=f"{message_id}",
                return_string="get_modification_tx issue",
            )

        if "merchantTransactionId" in transaction:
            # if modification Transaction returned, then
            #   tweak the 'message' structure
            #   store the updated message
            message["content"] = transaction
            message["header"]["class_name"] = "transactions"
            message["header"]["event_name"] = "modify"
            response = storeMessage(class_id, message)
            return response

    # If approved Transaction...
    elif class_name == "transactions" and event_name == "attempt succeeded":
        # ...and Transaction was generated by an AutoBill
        if "autoBillCycle" in message["content"]:
            # ...and if autobillCycle = 0 (initial billing on subscription)
            #   AutoBill status changed to 'Active', billingState changed to
            #   'Free/Trial' or 'Good Standing'.
            # ...OR If retryNumber > 0 (successful retry Transaction)
            #   AutoBill billingState changed to 'Good Standing'
            #
            # TODO: Handle free trial cases and non-zero transactions that are not retries
            if (
                int(message["content"]["autoBillCycle"]) == 0
                or int(message["content"]["retryNumber"]) > 0
            ):
                return get_subscription(message)
        # elif int(message['content']['retryNumber']) > 0:
        #     return get_subscription(message)
    # If declined Transaction...
    elif class_name == "transactions" and event_name == "attempt failed":
        # ...and Transaction was generated by an AutoBill
        if "autoBillCycle" in message["content"]:
            # ...and not initial billing (autobillCycle > 0 but not a
            # retry Transaction (retryNumber == 0) [aka, first
            # recurring billing decline] AutoBill billingState changed
            # to 'In Retry' (Soft Fail) or 'Unusable Payment Method' (Hard Fail)
            #
            # AutoBill status and billingState are affected by the first
            # recurring billing decline and the last retry. Easy enough to
            # identify the first retry. But, there is no data in the
            # Transaction to identify the last retry.
            #
            # So, config.RETRY_COUNT keeps the max retries value and the
            # AutoBill is fetched only on first and last retry decline
            if int(message["content"]["autoBillCycle"]) > 0 and (
                int(message["content"]["retryNumber"]) == 0
                or int(message["content"]["retryNumber"]) >= config.RETRY_COUNT
            ):
                return get_subscription(message)

    elif class_name == "entitlement":
        # If entitlement...no change to AutoBill status or billingState
        # No other message triggered
        pass

    elif class_name == "invoices":
        # If invoices message...no change to AutoBill status or billingState
        # No other message triggered
        pass

    elif class_name == "payment methods":
        # If payment methods message...no change to AutoBill status or billingState
        # Separate transactions message may have been triggered by Subscribe
        pass

    # Default return
    return api_return("200", return_string="OK", message_id=f"{message_id}")
