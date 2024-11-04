"""Utility functions
"""

import logging
import hmac
import hashlib
import json
import base64
import decimal
from datetime import datetime
import requests

import botocore.exceptions

# import sys

import config


def setup_custom_logger(name):
    """Global loging configuration

    Arguments:
        name {string} -- Global name for logger

    Returns:
        logger -- Logger with specified name
    """
    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s,%(msecs)d %(levelname)s "
            "%(module)s:%(lineno)d - %(message)s"
        )
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    # import config

    if config.DEBUG:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def validate(message_id: str, body: dict, sig: str):
    """validate - Calculate HMAC signature using key and compare to received signature

    Arguments:
        body {str} -- Message to be authenticated
        sig {str} -- Received signature

    Returns:
        boolean -- True iff received signature and calculated signature match
    """
    logger = logging.getLogger("root")
    logger.debug(
        "%s    Received signature: %s (%s)", message_id, sig, type(sig)
    )
    # logger.debug("body: %s", json.dumps(body, separators=(',', ':')).encode('utf-8'))
    if config.DEBUG > 2:
        logger.debug(
            "message_id: %s    body: %s",
            message_id,
            json.dumps(body, separators=(",", ":")).encode("utf-8"),
        )

    sig = bytes(sig.encode("utf-8"))

    body_hash = base64.b64encode(
        hmac.new(
            config.HMAC_KEY.encode("utf-8"),
            # The seperators remove the extra JSON whitespace
            json.dumps(body, separators=(",", ":")).encode("utf-8"),
            # str(body).encode('utf-8'),
            hashlib.sha256,
        ).digest()
    )

    logger.debug("%s    Calculated hash %s", message_id, body_hash)

    if sig == "TEST":
        # For local testing only
        return True

    if ct_compare(str(body_hash), str(sig)):
        return True
    return False


def json_serial(obj):
    """JSON serializer

    Not all objects are directly serializable by json.dumps. This
    function returns a serializable version of obj or raises
    TypeError

    Arguments:
        obj {object} -- object to serialize

    Returns:
        string -- Serializeable contents of {obj}
    """

    # from datetime import date, datetime
    # import decimal

    # logger = logging.getLogger('root')

    if isinstance(obj, (datetime, date)):
        # logger.debug("json_serial: datetime/date")
        return obj.isoformat()
    if isinstance(obj, (decimal.Decimal)):
        # logger.debug("json_serial: decimal")
        return str(obj)
    if isinstance(obj, set):
        # logger.debug("json_serial: set")
        return tuple(obj)
    return list(obj)
    # raise TypeError("Type %s not serializable" % type(obj))


def api_return(returnCode, **body):
    """Format return for AWS API Gateway

    Arguments:
        returnCode {integer} -- HTTP Status Code
        message {string} -- String message (escape before calling)

    Returns:
        dict -- Dictionary acceptable to AWS API Gateway
                (converted to JSON by handler):
                {
                    "isBase64Encoded": true|false,
                    "statusCode": httpStatusCode,
                    "headers": { "headerName": "headerValue", ... },
                    "multiValueHeaders": { "headerName": ["headerValue", "headerValue2", ...], ... },
                    "body": "..."
                }
    """
    api_return_obj = {
        "statusCode": returnCode,
        "body": f"{json.dumps(body, default=json_serial, separators=(',', ':'))}",
    }
    return api_return_obj


def verifySignature(string_to_verify, signature, shared_secret):
    return ct_compare(
        hmac.new(shared_secret, string_to_verify, hashlib.sha512).digest(),
        signature,
    )


def ct_compare(a, b):
    """
    Run a constant time comparison against two strings.

    Returns `True` if `a` and `b` are equal, `False` otherwise. `a` and `b`
    must both be the same length, or `False` is returned immediately.

    This function uses a constant time comparison to avoid timing attacks.
    It works by XORing each character in the two strings and ORing the
    results. If the final result is 0, the strings are equal.
    """

    if len(a) != len(b):
        return False

    result = 0
    for ch_a, ch_b in zip(a, b):
        result |= ord(ch_a) ^ ord(ch_b)

    return result == 0


def get_modification_tx(message_id: str, autobill: dict, event_timestamp: str):
    """get_modification_tx - Using SOAP Transaction.fetchByAutoBill via vin_proxy,
            get the Transactions for a specific AutoBill identified by VID.
            Based on the timestamp passed to the function find a Transaction
            which occurred within 30s containing the Vindicia special metadata
            'vin:type' that has a value of 'modify'.

    Arguments:
        autobill {dict} -- Subscribe AutoBill object as python dictionary
        event_timestamp {str} -- String, RFC 3339 datetime sepcifying a time
            frame to use for Transaction selection

    Returns:
        dict -- Subscribe Transaction object
    """

    logger = logging.getLogger("root")
    logger.debug("Fetching Transactions for AutoBill >%s<", autobill["VID"])

    try:
        vid = autobill["VID"]
        # Convert naive, RFC 3339, str event_timestamp to an aware datetime object
        # Transaction.timestamp from Subscribe is an aware ISO 8601 string
        event_timestamp = config.timezone.localize(
            datetime.strptime(event_timestamp, "%Y-%m-%dT%H:%M:%S.%f")
        )
    except Exception:
        logger.exception(
            "Error with search parameters for get_modification_tx"
        )
        return api_return(
            "400",
            message_id=f"{message_id}",
            return_string="ERROR Cannot determine search parameters for get_modification_tx",
        )

    # Base Transaction.fetchByAutoBill() method parameters.
    fetchParameters = {"srd": "", "autobill": {"VID": vid}}
    response = vin_proxy("Transaction.fetchByAutobill", fetchParameters)
    # logger.debug("%s", json.dumps(response, default=json_serial, indent=4))
    if response["return"]["returnCode"] != 200:
        return response
    for transaction in response["transactions"]:
        # Loop over returned Transactions checking for proximity to
        # event_timestamp and if it contains the'vin:type' = 'modify' metadata
        diff = event_timestamp - transaction["timestamp"]
        if diff.total_seconds() < 300:
            for nameValue in transaction["nameValues"]:
                if nameValue["name"] == "vin:type":
                    logger.info(
                        "Found modification Transaction >%s< within %ss of event_timestamp",
                        transaction["merchantTransactionId"],
                        diff.total_seconds(),
                    )
                    return transaction
    return None


def get_subscription(id: dict):
    """get_subscription - Using SOAP AutoBill.fetchByVid via vinProxy,
            get a specific AutoBill identified its Vindicia identifier.
            Based on the timestamp passed to the function find a Transaction
            which occurred within 30s containing the Vindicia special metadata
            'vin:type' that has a value of 'modify'.

    Arguments:
        message {dict} -- Triggering Push Message. Use the 'autobillVID' in the
                          message to fetch the related AutoBill and re-use some
                          of the notification headers are re-used when storing
                          the fetched obgject

    Returns:
        dict -- Always returns a 202 'returnCode' but 'returnString' is
                dependent on success of operations in this function
    """

    logger = logging.getLogger("root")

    # Base AutoBill.fetchByVid() method parameters.
    try:
        fetchParameters = {"srd": "", "vid": message["content"]["autobillVID"]}
        logger.debug(
            "%s    Fetching AutoBill >%s<",
            message["header"]["message_id"],
            fetchParameters["vid"],
        )
    except Exception:
        logger.warning("Cannot identify autobillVID")
        return api_return(
            "202",
            return_string=f"{message['header']['message_id']} Cannot identify related AutoBill",
        )

    # Use SOAP proxy to perform AutoBill.fetchByVid()
    try:
        response = vin_proxy("AutoBill.fetchByVid", fetchParameters)
    except Exception:
        logger.warning(
            "%s    Error with AutoBill.fetchByVid",
            message["header"]["message_id"],
        )
        return api_return(
            "202",
            return_string=f"{message['header']['message_id']} Error fetching related AutoBill",
        )
    # logger.debug("%s", json.dumps(response, default=json_serial, indent=4))

    # if AutoBll returned, then
    #   tweak the 'message' structure
    #   store the updated message
    try:
        merchantAutoBillId = response["autobill"]["merchantAutoBillId"]
        message["content"] = response["autobill"]
        message["header"]["class_name"] = "autobills"
        message["header"]["event_name"] = "state change"
        response = storeMessage(merchantAutoBillId, message)
        if int(response["statusCode"]) == 202:
            return api_return("202", return_string="OK")
        else:
            return api_return("202", return_string=f"{response['body']}")
    except Exception as e:
        logger.warning(
            "%s %s/%s    AutoBill not found\n%s\n%s",
            message["header"]["message_id"],
            message["header"]["class_name"],
            message["header"]["event_name"],
            response,
            e,
        )
        return api_return(
            "202",
            message_id=(
                f"{message['header']['message_id']} "
                f"{message['header']['class_name']}/"
                f"{message['header']['event_name']}"
            ),
            return_string="Related AutoBill not found",
        )


# def vinProxy(method: str, requestBody: dict) -> xsd.CompoundValue:
#     """vinProxy Perform Subscribe SOAP API call

#     Arguments:
#         method {str} -- Subscribe fully qualified API method
#         requestBody {dict} -- Structure of specific Subscribe API method inputs

#     Returns:
#         xsd.CompoundValue -- Data object for a specific xsd:complexType
#     """

#     logger = logging.getLogger('root')
#     if config.DEBUG:
#         logger.setLevel(logging.DEBUG)

#     version = str(config.VIN_VERSION)
#     vinClass = method.split(".")[0]
#     vinMethod = method.split(".")[1]
#     history = HistoryPlugin()

#     """Add auth to request"""
#     requestBody['auth'] = {
#         'version': version,
#         'login': config.API_CREDS[0],
#         'password': config.API_CREDS[1],
#         'userAgent': config.USERAGENT
#     }
#     if config.DEBUG >= 5:
#         logger.debug("%s.%s\n%s", vinClass, vinMethod, json.dumps(requestBody, indent=4))

#     # preReturn = subscription_dryrun(jsonRequest)

#     """ Create new SOAP Client """
#     myTransport = Transport(timeout=10)
#     try:
#         client = Client(
#             wsdl='https://soap.vindicia.com/'+version+'/'+vinClass+'.wsdl',
#             plugins=[history],
#             transport=myTransport
#         )
#     except Exception:
#         logger.exception('Fatal error in vinProxy')
#         return api_return("400", return_string = "Fatal error in vinProxy")
#         # raise sys.exc_info()[0]

#     if (config.VINENV != 'Production'):
#         # change the SOAP address defined in WSDL if not using Subscribe Production
#         service = client.create_service(
#             '{http://soap.vindicia.com/v'+version.replace('.','_')+'/'+vinClass+'}'+vinClass+'Binding',
#             'https://soap.staging.us-west.vindicia.com/soap.pl')
#     else:
#         service = client.service

#     try:
#         with client.settings(strict=False, xml_huge_tree=True):
#             methodResponse = service[vinMethod](**requestBody)
#     except Exception:
#         logger.exception('SOAP API failure')
#         return api_return("400", return_string = "SOAP API failure")

#     """Remove the raw elements from the return (prefixed by '_')"""
#     this = helpers.serialize_object(methodResponse)
#     if "_raw_elements" in this['return']:
#         del this['return']['_raw_elements']

#     """ Work around for Subscribe SOAP returnString issue """
#     from lxml import etree
#     x = xmltodict.parse(etree.tostring(history.last_received["envelope"], encoding="UTF-8"))
#     this['return']['returnString'] = x['soap:Envelope']['soap:Body'][vinMethod+'Response']['return']['returnString']['#text']

#     logger.info(f"{this['return']['soapId']}\t{this['return']['returnCode']},\t{this['return']['returnString']}\t{vinMethod}")

#     if config.DEBUG >= 4:
#         logger.debug("Subscribe SOAP API Return: %s\n%s", type(this), this)
#     return this


def storeMessage(class_id: str, message: dict):
    """storeMessage Store message onto S3

    Arguments:
        class_id {str} -- Merchant identifier or Vindicia identifier for
            Subscribe object
        message {dict} -- Subscribe Push Notification message to store

    Returns:
        dict -- Suitable API Gateway response dictionary with 'statusCode'
                indicating success or failure
    """
    import boto3

    logger = logging.getLogger("root")

    logger.debug(
        "%s    Storing message to S3", message["header"]["message_id"]
    )

    # Identify the S3 bucket
    try:
        s3 = boto3.resource("s3", config.REGION_NAME)
    except (boto3.exceptions.BotoCoreError, boto3.exceptions.ClientError) as e:
        logger.exception("Error setting S3 resource:\n%s", e)
        return api_return(
            "409",
            return_string=(
                f"{message['header']['message_id']} ERROR: Storing message"
            ),
        )

    try:
        # Construct the S3 Item to store
        Item = {
            "message_id": message["header"]["message_id"],
            "class_id": class_id,
            "class_name": message["header"]["class_name"],
            "event_name": message["header"]["event_name"],
            "merchant_vid": message["header"]["merchant_vid"],
            "event_timestamp": message["header"]["event_timestamp"],
            "soap_version": message["header"]["soap_version"],
            # 'notification': json.dumps(message['content']),
            "notification": message["content"],
        }
    except KeyError as e:
        logger.exception("ERROR: Cannot set message component %s", e)
        return api_return(
            "410",
            return_string=(
                f"{message['header']['message_id']} "
                "ERROR: Cannot set message component"
            ),
        )

    try:
        # Set the S3 bucket and object specifics
        timestamp_formats = [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ]

        try:
            timestamp = None
            for timestamp_format in timestamp_formats:
                try:
                    timestamp = config.timezone.localize(
                        datetime.strptime(
                            message["header"]["event_timestamp"],
                            timestamp_format,
                        )
                    )
                    break
                except ValueError:
                    continue

            if not timestamp:
                raise ValueError("Invalid timestamp format")

            path = (
                timestamp.strftime("%Y%m%d")
                + "/"
                + message["header"]["class_name"]
                + "/"
                + message["header"]["event_name"]
                + "/"
            )

        except (ValueError, KeyError) as e:
            logger.exception("Cannot parse event_timestamp: %s", e)
            return api_return(
                "411",
                return_string=(
                    f"{message['header']['message_id']} event_timestamp error"
                ),
            )

        file_name = path + message["header"]["message_id"]
        s3.Bucket(config.BUCKET_NAME).put_object(
            Key=file_name, Body=json.dumps(Item, default=json_serial)
        )
        logger.info(
            "%s stored to %s/%s",
            message["header"]["message_id"],
            config.BUCKET_NAME,
            file_name,
        )
    except (
        botocore.exceptions.BotoCoreError,
        botocore.exceptions.ClientError,
        KeyError,
    ) as e:
        if e.response["Error"]["Code"] == "NoSuchBucket":
            logger.exception("Specified bucket does not exist: %s", e)
        else:
            logger.exception("Error storing message: %s", e)
        return api_return(
            "411",
            return_string=(
                f" Error storing message: {message['header']['message_id']}"
            ),
        )

    return api_return(
        "200", return_string=f"{message['header']['message_id']} OK"
    )


def fetch_transactions(subscription_identifier):
    base_url = os.getenv("API_BASE_URL")
    endpoint = "/transactions"

    username = os.getenv("API_USERNAME")
    password = os.getenv("API_PASSWORD")

    headers = {"Accept": "application/json"}

    params = {"subscription": subscription_identifier}

    try:
        # Prepare the request
        req = requests.Request(
            "GET",
            f"{base_url}{endpoint}",
            auth=(username, password),
            headers=headers,
            params=params,
        )
        prepared_req = req.prepare()

        # Send the request
        session = requests.Session()
        session.auth = (username, password)
        response = session.send(prepared_req)

        if response.status_code == 200:
            transactions = response.json()
            return transactions
        else:
            print(f"\nError: Status Code {response.status_code}")

            # Print raw request
            print("\nRaw Request:")
            print(f"URL: {prepared_req.url}")
            print(f"Method: {prepared_req.method}")
            print("Headers:")
            for header, value in prepared_req.headers.items():
                print(f"  {header}: {value}")
            print(f"Body: {prepared_req.body}")

            # Print raw response
            print("\nRaw Response:")
            print(f"Headers: {response.headers}")
            print(f"Content: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Network error occurred: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error occurred: {e}")
        return None


def fetch_transaction(id: str):
    """
    Fetches transaction for the given identifier.

    Args:
        subscription_identifier (str): The identifier of the subscription to fetch transactions for.

    Returns:
        dict or None: A dictionary containing the transactions, or None if an error occurred.
    """
    base_url = config.os.getenv("API_BASE_URL")
    endpoint = "/transactions"

    username = config.API_CREDS[0]
    password = config.API_CREDS[1]

    headers = {"Accept": "application/json"}

    # params = {"subscription": subscription_identifier}

    try:
        # Prepare the request
        req = requests.Request(
            "GET",
            f"{base_url}{endpoint}/{id}",
            auth=(username, password),
            headers=headers,
            # params=params,
        )
        prepared_req = req.prepare()

        # Send the request
        session = requests.Session()
        session.auth = (username, password)
        response = session.send(prepared_req)

        if response.status_code == 200:
            transactions = response.json()
            return transactions
        else:
            print(f"\nError: Status Code {response.status_code}")

            # Print raw request
            print("\nRaw Request:")
            print(f"URL: {prepared_req.url}")
            print(f"Method: {prepared_req.method}")
            print("Headers:")
            for header, value in prepared_req.headers.items():
                print(f"  {header}: {value}")
            print(f"Body: {prepared_req.body}")

            # Print raw response
            print("\nRaw Response:")
            print(f"Headers: {response.headers}")
            print(f"Content: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Network error occurred: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error occurred: {e}")
        return None
