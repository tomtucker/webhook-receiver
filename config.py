import os
import logging
import pytz
from utils import api_return, setup_custom_logger

# Set the timezone to match CashBox
timezone = pytz.timezone("America/Los_Angeles")

# Set global variables from environment
try:
    HMAC_KEY = os.environ['hmac_key']
    DEBUG = int(os.environ['debug'])
    REGION_NAME = os.environ['regionName']
    BUCKET_NAME = os.environ['s3Bucket']
    API_CREDS = os.environ['api_key'].split(":")
    VIN_VERSION = os.environ['vin_Version']
    USERAGENT = 'eventManager 1.0',
    RETRY_COUNT = 3
    VINENV = os.environ['vinEnv']
except Exception:
    # No logger has been defined yet so print the traceback and return an error
    import traceback
    traceback.print_exc()
    api_return("400", "ERROR: Missing required environment >" + "<")

# Setup Logging - logging to CloudWatch Log
logger = setup_custom_logger('root')
