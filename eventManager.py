import json
import boto3
import os
import logging
import datetime

import config
# import hmacValidation as auth
from utils import *

def eventManager(event: dict):
    """eventManager Process a CashBox Push Message

    Arguments:
        event {dict} -- dictionary containing a CashBox Push Notification
                        message and HTTP Headers

    Returns:
        dict -- api_return containing a statusCode and message
    """    
    logger = logging.getLogger('root')

    # authentication of message against received HMAC signature
    try:
        # logger.debug("Received signature: %s", msgSig)
        if (validate(event['body'], event['headers']['X-Webhook-Signature'])):
            pass
        else:
            logger.exception('Received signature >%s< does not match', event['headers']['X-Webhook-Signature'])
            return api_return("403", "Forbidden")
    except Exception:
        logger.exception('Signature Validation error:')
        return api_return("403", "Forbidden")

    # Set specific message properties from JSON body 'header'
    message = json.loads(event['body'])
    try:
        class_name = message['header']['class_name']
        event_name = message['header']['event_name']
        message_id = message['header']['message_id']
        event_timestamp = message['header']['event_timestamp']
    except Exception:
        logger.exception("Cannot parse message header")
        return api_return("406", "ERROR: Cannot parse message header")

    # These are the object IDs expected for each class_name
    # Note inconsistent case of 'merchantAutobillId' for entilement messages.
    # That's the way it is received
    classIds = {
        'accounts': 'merchantAccountId',
        'adjustments': 'merchantRefundId',
        'autobills': 'merchantAutoBillId',
        'transactions': 'merchantTransactionId',
        'entitlement': 'merchantAccountId',
        'invoices': 'invoice_id',
        'payment methods': 'merchantPaymentMethodId'
    }

    # This loop sets the class_id for the object based on the class_name in the messsage or uses
    # 'VID' if the expected class_id is not found
    for key, value in classIds.items():
        if class_name == key:
            logger.debug("%s/%s. Looking for %s", class_name, event_name, value)

            # DGD-1786: Handle KeyError for malformed objects missing Merchant
            # class identifiers
            if class_name == "autobills" and event_name == "modify":
                # Special handling for autobills/modify messages:
                # The message CONTAINS the object instead of IS the object
                try:
                    if message['content']['autobill']['merchantAutoBillId']:
                        class_id = message['content']['autobill']['merchantAutoBillId']
                    else:
                        class_id = message['content']['autobill']['VID']
                        logger.warn("%s/%s: Using \'VID\' instead of %s for : message_id=%s", class_name,
                            event_name, classIds[class_name][1], message_id)
                    break
                except Exception:
                    logger.exception("Cannot set class ID for message_id >%s<", message_id)
                    return api_return("400", "Cannot set class ID for message_id=" + message_id)
            elif class_name == "accounts" and event_name == "data change":
                # Special handling for accounts/data change messages:
                # The message CONTAINS the object instead of IS the object
                try:
                    if message['content']['account']['merchantAccountId']:
                        class_id = message['content']['account']['merchantAccountId']
                    else:
                        class_id = message['content']['account']['VID']
                        logger.warn("%s/%s: Using \'VID\' instead of %s: message_id=%s", class_name,
                            event_name, value, message_id)
                    break
                except Exception:
                    logger.exception('Cannot set class ID for message_id >%s<', message_id)
                    return api_return("400", "Cannot set class ID for message_id=" + message_id)
            else:
                try:
                    if message['content'][value]:
                        class_id = message['content'][value]
                    else:
                        class_id = message['content']['VID']
                        logger.warn("%s/%s: Using \'VID\' instead of %s for message_id=%s", class_name,
                            event_name, value, message_id)
                    break
                except Exception:
                    logger.excpetion("Cannot set class ID for message_id >%s<", message_id)
                    return api_return("400", "Cannot set class ID for message")

    # Store the message
    response = storeMessage(class_id, message)

    if int(response['statusCode']) > 202:
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
        transaction = getModificationTx(message['content']['autobill'], event_timestamp)
        if transaction is None or 'merchantTransactionId' not in transaction:
            # No modification Transactions found
            logger.warn("Modification Transaction not found for message_id >%s<", message_id)
            return api_return("202", "Modification Transaction not found")
        elif 'return' in transaction:
            logger.warn("getModificationTx issue:\n%s", json.dumps(response, indent=4))
        elif 'merchantTransactionId' in transaction:
            # if modification Transaction returned, then
            #   tweak the 'message' structure
            #   store the updated message
            message['content'] = transaction
            message['header']['class_name'] = 'transactions'
            message['header']['event_name'] = 'modify'
            response = storeMessage(class_id, message)
            return response
        else:
            # Possible to not find a modification Transaction if no
            # pro-rated charge for AutoBill.modify() operation
            pass
    
    # If approved Transaction...
    elif class_name == "transactions" and event_name == "attempt succeeded":
        # ...and Transaction was generated by an AutoBill
        if 'autoBillCycle' in message['content']:
            # ...and if autobillCycle = 0 (initial billing on subscription)
            #   AutoBill status changed to 'Active', billingState changed to
            #   'Free/Trial' or 'Good Standing'
            # ...OR If retryNumber > 0 (successful retry Transaction)
            #   AutoBill billingState changed to 'Good Standing'
            if (int(message['content']['autoBillCycle']) == 0) or \
                (int(message['content']['retryNumber']) > 0):
                return getAutoBill(message)
        # elif int(message['content']['retryNumber']) > 0:
        #     return getAutoBill(message)
    # If declined Transaction...
    elif class_name == "transactions" and event_name == "attempt failed":
        # ...and Transaction was generated by an AutoBill
        if 'autoBillCycle' in message['content']:
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
            if (int(message['content']['autoBillCycle']) > 0
                and (
                    int(message['content']['retryNumber']) == 0
                    or int(message['content']['retryNumber']) >= config.RETRY_COUNT
                    )
                ):
                return getAutoBill(message)

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
        # Separate transactions message triggered by CashBox
        pass

    # Default return
    return api_return("202", "OK")
