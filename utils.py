"""Utility functions
"""

import logging
import hmac, hashlib, json, base64
import sys
from datetime import datetime, timedelta

"""Zeep: Python SOAP client
    https://python-zeep.readthedocs.io/en/master/
"""
from zeep import Client
from zeep import helpers
from zeep import xsd
from zeep.transports import Transport

""" Zeep does not populate the returned dict with value of {returnString} from
    CashBox SOAP responses. To do this use the Zeep History Class and 2
    additonal modules:
        Zeep History Plugin - https://python-zeep.readthedocs.io/en/master/plugins.html)
        lxml - https://pypi.org/project/lxml/ (installed with Zeep)
        xmltodict - https://pypi.org/project/xmltodict/ (use pip to install)

    To register the Zeep plugin you need to pass it to the Zeep client.
    Plugins are always executed sequentially:

        history = HistoryPlugin()
        client = Client(
            wsdl='https://soap.vindicia.com/22.0/Campaign.wsdl',
            plugins=[history]
        )
"""
from zeep.plugins import HistoryPlugin
from lxml import etree
import xmltodict

import config

def setup_custom_logger(name):
    """Global loging configuration

    Arguments:
        name {string} -- Global name for logger

    Returns:
        logger -- Logger with specified name
    """
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    return logger

# def api_exception(type, isError, message):
#     """ Helper function to suppress stack trace from caller.

#     Only necessary if NOT using Lambda Proxy integration
    
#     Arguments:
#         type {integer} -- HTTP Status code
#         isError {bool} -- Error flag
#         message {string} -- Error message to return to caller
    
#     Returns:
#         string -- Serialized JSON
#     """
#     import json
#     api_exception_obj = {
#         "type": type,
#         "isError": isError,
#         "message": message
#     }
#     return json.dumps(api_exception_obj)

# class LambdaException(Exception):
#     """Simple Exception wrapper
    
#     Arguments:
#         Exception {Exception} -- Exception to catch to suppress stack trace
#         when not using API Gateway Proxy integration to Lambda function
#     """
#     pass

def validate(body: dict, sig: str):
    """validate - Calculate HMAC signature using key and compare to received signature
    
    Arguments:
        body {str} -- Message to be authenticated
        sig {str} -- Received signature
    
    Returns:
        boolean -- True iff received signature and calculated signature match
    """
    logger = logging.getLogger('root')
    logger.debug("Received signature: %s (%s)", sig, type(sig))
    logger.debug("body: %s", body)

    sig = bytes(sig.encode('utf-8'))

    body_hash = base64.b64encode(
        hmac.new(
            config.HMAC_KEY.encode('utf-8'),
            # The seperators remove the extra JSON whitespace
            json.dumps(body, separators=(',', ':')).encode('utf-8'),
            hashlib.sha256
        ).digest()
    )

    logger.debug("Calculated hash \'%s\'", body_hash)

    if sig == 'TEST':
        # For local testing only
        return True

    if ct_compare(str(body_hash), str(sig)):
        return True
    else:
        return False

def json_serial(obj):
    """JSON serializer
    
    Not all objects are directly serializable json.dumps. This
    function returns a serializable version of obj or raises
    TypeError
    
    Arguments:
        obj {object} -- object to serialize
    
    Raises:
        TypeError -- [description]
    
    Returns:
        string -- Serializeable contents of {obj}
    """

    from datetime import date, datetime
    import decimal

    logger = logging.getLogger('root')

    if isinstance(obj, (datetime, date)):
        logger.info("json_serial: datetime/date")
        return obj.isoformat()
    elif isinstance(obj, (decimal.Decimal)):
        logger.info("json_serial: decimal")
        return str(obj)
    else:
        logger.info("json_serial: other")
    return list(obj)
    # raise TypeError("Type %s not serializable" % type(obj))

def api_return(returnCode, message):
    """Format return for AWS API Gateway
    
    Arguments:
        returnCode {integer} -- HTTP Status Code
        message {string} -- String message (escape before calling)
    
    Returns:
        dict -- Dictionary acceptable to AWS API Gateway
                (converted to JSON by handler)
    """
    api_return_obj = {"statusCode": returnCode, "body": message}
    return api_return_obj

def verifySignature(string_to_verify, signature, shared_secret):
    return ct_compare(hmac.new(shared_secret, 
		string_to_verify, hashlib.sha512).digest(), signature)

def ct_compare(a, b):
    """
	** From Django source **
	Run a constant time comparison against two strings
	Returns true if a and b are equal.
	a and b must both be the same length, or False is 
	returned immediately
    """

    if len(a) != len(b):
       return False

    result = 0
    for ch_a, ch_b in zip(a, b):
        result |= ord(ch_a) ^ ord(ch_b)

    return result == 0

def getModificationTx(autobill: dict, event_timestamp: str):
    """getModificationTx Using SOAP Transaction.fetchByAutoBill via vinProxy,
            get the Transactions for a specific AutoBill identified by VID.
            Based on the timestamp passed to the function find a Transaction
            which occurred within 30s containing the Vindicia special metadata
            'vin:type' that has a value of 'modify'.
    
    Arguments:
        autobill {dict} -- CashBox AutoBill object as python dictionary
        event_timestamp {str} -- String, RFC 3339 datetime sepcifying a time
            frame to use for Transaction selection
    
    Returns:
        dict -- CashBox Transaction object
    """

    logger = logging.getLogger('root')
    logger.debug("Fetching Transactions for AutoBill >%s<", autobill['VID'])

    try:
        vid = autobill['VID']
        # Convert naive, RFC 3339, str event_timestamp to an aware datetime object
        # Transaction.timestamp from CashBox is an aware ISO 8601 string
        event_timestamp = config.timezone.localize(
            datetime.strptime(event_timestamp, "%Y-%m-%d %H:%M:%S")
        )
    except Exception as e:
        logger.exception(e)
        return api_return(500, "ERROR Cannot determine search parameters for getModificationTx")

    # Base Transaction.fetchByAutoBill() method parameters.
    fetchParameters = {
        'srd': '',
        'autobill': {
            'VID': vid
        }
    }
    response = vinProxy('Transaction.fetchByAutobill', fetchParameters)
    # logger.debug("%s", json.dumps(response, default=json_serial, indent=4))
    if (response['return']['returnCode'] != 200):
        return response
    for transaction in response['transactions']:
        # Loop over returned Transactions checking for proximity to
        # event_timestamp and if it contains the'vin:type' = 'modify' metadata
        diff = event_timestamp - transaction['timestamp']
        if diff.total_seconds() < 300:
            for nameValue in transaction['nameValues']:
                if nameValue['name'] == 'vin:type':
                    logger.info("Found modification Transaction >%s< within %ss of event_timestamp",
                         transaction['merchantTransactionId'], diff.total_seconds())
                    return transaction
    return None

def getAutoBill(vid: str):
    """getAutoBill - Using SOAP AutoBill.fetchByVid via vinProxy,
            get a specific AutoBill identified its Vindicia identifier.
            Based on the timestamp passed to the function find a Transaction
            which occurred within 30s containing the Vindicia special metadata
            'vin:type' that has a value of 'modify'.
    
    Arguments:
        autobill {str} -- Vindicia identifier for a specific AutoBill object
    
    Returns:
        dict -- CashBox AutoBill object as dictionary
    """

    logger = logging.getLogger('root')
    logger.debug("Fetching AutoBill >%s<", vid)

    # Base AutoBill.fetchByVid() method parameters.
    fetchParameters = {
        'srd': '',
        'VID': vid
    }
    response = vinProxy('AutoBill.fetchByVid', fetchParameters)
    # logger.debug("%s", json.dumps(response, default=json_serial, indent=4))
    return response

def vinProxy(method: str, requestBody: dict) -> xsd.CompoundValue:
    """vinProxy Perform CashBox SOAP API call
    
    Arguments:
        method {str} -- CashBox fully qualified API method
        requestBody {dict} -- Structure of specific CashBox API method inputs
    
    Returns:
        xsd.CompoundValue -- Data object for a specific xsd:complexType
    """

    logger = logging.getLogger('root')
    logger.setLevel(logging.DEBUG)

    version = str(config.VIN_VERSION)
    vinClass = method.split(".")[0]
    vinMethod = method.split(".")[1]
    history = HistoryPlugin()

    """Add auth to request"""
    requestBody['auth'] = {
        'version': version,
        'login': config.API_CREDS[0],
        'password': config.API_CREDS[1],
        'userAgent': config.USERAGENT
    }
    if config.DEBUG >= 5:
        logger.debug("%s.%s\n%s", vinClass, vinMethod, json.dumps(requestBody, indent=4))

    # preReturn = subscription_dryrun(jsonRequest)

    """ Create new SOAP Client """
    myTransport = Transport(timeout=10)
    try:
        client = Client(
            wsdl='https://soap.vindicia.com/'+version+'/'+vinClass+'.wsdl',
            plugins=[history],
            transport=myTransport
        )
    except Exception as e:
        logger.exception(e)
        raise sys.exc_info()[0]

    """ Override SOAP service address for Prodtest """
    """ Comment next 3 lines for Production """
    service = client.create_service(
        '{http://soap.vindicia.com/v'+version.replace('.','_')+'/'+vinClass+'}'+vinClass+'Binding',
        'https://soap.prodtest.sj.vindicia.com/soap.pl')

    try:
        with client.settings(strict=False, xml_huge_tree=True):
            methodResponse = service[vinMethod](**requestBody)
    except Exception as e:
        logger.exception('SOAP failure: %s', e)
        return api_return(502, "Invalid JSON for method")

    logger.info('%s    %s    %s    %s',
        methodResponse['return']['soapId'],
        methodResponse['return']['returnCode'],
        methodResponse['return']['returnString'],
        vinMethod)

    """Remove the raw elements from the return (prefixed by '_')"""
    this = helpers.serialize_object(methodResponse)
    if "_raw_elements" in this['return']:
        del this['return']['_raw_elements']
    if config.DEBUG >= 5:
        logger.info("this: %s", type(this))

    """ Work around for CashBox SOAP return issue """
    from lxml import etree
    x = xmltodict.parse(etree.tostring(history.last_received["envelope"], encoding="UTF-8"))
    this['return']['returnString'] = x['soap:Envelope']['soap:Body'][vinMethod+'Response']['return']['returnString']['#text']

    return this

def storeMessage(class_id: str, message: dict):
    """storeMessage Store message onto S3
    
    Arguments:
        class_id {str} -- Merchant identifier or Vindicia identifier for
            CashBox object
        message {dict} -- CashBox Push Notification message to store
    
    Returns:
        dict -- Suitable API Gateway response dictionary with 'statusCode' indicating
                success or failure
    """
    import boto3

    logger = logging.getLogger('root')
    logger.setLevel(logging.DEBUG)
    logger.debug("Storing message to S3")

    # Identify the S3 bucket
    try:
        s3 = boto3.resource(
            's3',
            config.REGION_NAME
            )
    except Exception as e:
        logger.exception('Error setting S3 resource:\n%s', e)
        return api_return("409", "ERROR: Cannot set S3 Bucket")

    try:
        # Construct the S3 Item to store
        Item = {
            'message_id': message['header']['message_id'],
            'class_id': class_id,
            'class_name': message['header']['class_name'],
            'event_name': message['header']['event_name'],
            'merchant_vid': message['header']['merchant_vid'],
            'event_timestamp': message['header']['event_timestamp'],
            'soap_version': message['header']['soap_version'],
            #'notification': json.dumps(message['content']),
            'notification': message['content'],
        }
    except Exception as e:
        logger.exception(e)
        return api_return("410", "ERROR: Error setting message component")

    try:
        # Set the S3 bucket and object specifics
        directory = 'vindicia/' + message['header']['class_name'] + '/'
        fileName = directory + message['header']['message_id']
        s3.Bucket(config.BUCKET_NAME).put_object(Key=fileName, Body=json.dumps(Item))
        logger.info("Stored message >%s< into %s/%s", message['header']['message_id'], config.BUCKET_NAME, fileName)
 
    except Exception as e:
        logger.exception(e)
        return api_return("411", "Error storing message")

    return api_return("202", "OK")
    