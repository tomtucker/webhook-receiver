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
    import config
    if config.DEBUG:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger

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
    # logger.debug("body: %s", json.dumps(body, separators=(',', ':')).encode('utf-8'))
    logger.debug("body: (%s) %s", type(body), body)

    sig = bytes(sig.encode('utf-8'))

    body_hash = base64.b64encode(
        hmac.new(
            config.HMAC_KEY.encode('utf-8'),
            # The seperators remove the extra JSON whitespace
            # json.dumps(body, separators=(',', ':')).encode('utf-8'),
            str(body).encode('utf-8'),
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
        logger.debug("json_serial: datetime/date")
        return obj.isoformat()
    elif isinstance(obj, (decimal.Decimal)):
        logger.debug("json_serial: decimal")
        return str(obj)
    else:
        logger.debug("json_serial: other")
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
    except Exception:
        logger.exception("Error with search parameters for getModificationTx")
        return api_return("400", "ERROR Cannot determine search parameters for getModificationTx")

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

def getAutoBill(message: dict):
    """getAutoBill - Using SOAP AutoBill.fetchByVid via vinProxy,
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
        dict -- Always returns a 202 'returnCode' but 'returnString' is dependent
                on success of operations in this function
    """

    logger = logging.getLogger('root')

    # Base AutoBill.fetchByVid() method parameters.
    try:
        fetchParameters = {
            'srd': '',
            'vid': message['content']['autobillVID']
        }
        logger.debug("Fetching AutoBill >%s<", fetchParameters['vid'])
    except Exception:
        logger.exception("Cannot identify autobillVID")
        return api_return("202", "Cannot identify related AutoBill")

    # Use SOAP proxy to perform AutoBill.fetchByVid()
    try:
        response = vinProxy('AutoBill.fetchByVid', fetchParameters)
    except Exception:
        logger.exception("Error with AutoBill.fetchByVid")
        return api_return("202", "Error fetching related AutoBill")
    # logger.debug("%s", json.dumps(response, default=json_serial, indent=4))

    # if AutoBll returned, then
    #   tweak the 'message' structure
    #   store the updated message
    try:
        merchantAutoBillId = response['autobill']['merchantAutoBillId']
        message['content'] = json.dumps(response['autobill'], default=json_serial, separators=(',', ':')).encode('utf-8')
        message['header']['class_name'] = 'autobills'
        message['header']['event_name'] = 'state change'
        response = storeMessage(merchantAutoBillId, message)
        if int(response['statusCode']) == 202:
            return api_return("202", "OK")
        else:
            return api_return("202", response['body'])
    except Exception:
        logger.exception("AutoBill not found for message_id >%s<", message['header']['message_id'])
        return api_return("202", "Related AutoBill not found")

    return api_return("202", "Unreachable code")

def vinProxy(method: str, requestBody: dict) -> xsd.CompoundValue:
    """vinProxy Perform CashBox SOAP API call
    
    Arguments:
        method {str} -- CashBox fully qualified API method
        requestBody {dict} -- Structure of specific CashBox API method inputs
    
    Returns:
        xsd.CompoundValue -- Data object for a specific xsd:complexType
    """

    logger = logging.getLogger('root')
    # logger.setLevel(logging.DEBUG)

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
    except Exception:
        logger.exception('Fatal error in vinProxy')
        raise sys.exc_info()[0]

    """ Override SOAP service address for Prodtest """
    """ Comment next 3 lines for Production """
    service = client.create_service(
        '{http://soap.vindicia.com/v'+version.replace('.','_')+'/'+vinClass+'}'+vinClass+'Binding',
        'https://soap.prodtest.sj.vindicia.com/soap.pl')

    try:
        with client.settings(strict=False, xml_huge_tree=True):
            methodResponse = service[vinMethod](**requestBody)
    except Exception:
        logger.exception('SOAP API failure')
        return api_return("400", "SOAP API failure")

    """Remove the raw elements from the return (prefixed by '_')"""
    this = helpers.serialize_object(methodResponse)
    if "_raw_elements" in this['return']:
        del this['return']['_raw_elements']

    """ Work around for CashBox SOAP returnString issue """
    from lxml import etree
    x = xmltodict.parse(etree.tostring(history.last_received["envelope"], encoding="UTF-8"))
    this['return']['returnString'] = x['soap:Envelope']['soap:Body'][vinMethod+'Response']['return']['returnString']['#text']

    logger.info('%s    %s    %s    %s',
        this['return']['soapId'],
        this['return']['returnCode'],
        this['return']['returnString'],
        vinMethod)

    if config.DEBUG >= 4:
        logger.info("CashBox SOAP API Return: %s\n%s", type(this), this)

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
    logger.debug("Storing message to S3")

    # Identify the S3 bucket
    try:
        s3 = boto3.resource(
            's3',
            config.REGION_NAME
            )
    except Exception:
        logger.exception('Error setting S3 resource')
        return api_return("409", "ERROR: Storing message")

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
    except Exception:
        logger.exception("ERROR: Cannot set message component")
        return api_return("410", "ERROR: Cannot set message component")

    try:
        # Set the S3 bucket and object specifics
        path = 'vindicia/' + message['header']['class_name'] + '/' + message['header']['event_name'] + '/'
        fileName = path + message['header']['message_id']
        s3.Bucket(config.BUCKET_NAME).put_object(Key=fileName, Body=json.dumps(Item, default=json_serial))
        logger.info("Stored message >%s< into %s/%s", message['header']['message_id'], config.BUCKET_NAME, fileName)
    except Exception:
        logger.exception("Error storing message")
        return api_return("411", "Error storing message")

    return api_return("202", "OK")
    