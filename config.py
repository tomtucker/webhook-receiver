"""
This module sets up global configuration variables for the application,
including:

- Timezone: Sets the timezone to "America/Los_Angeles" to match CashBox.
- Environment variables: Reads various environment variables and assigns them
  to global variables, such as HMAC_KEY, DEBUG, REGION_NAME, BUCKET_NAME,
  API_CREDS, VIN_VERSION, USERAGENT, RETRY_COUNT, and VINENV.
- Logging: Sets up a custom logger using the `setup_custom_logger` function
  from the `utils` module.

If any required environment variables are missing, the module will print the
traceback and return an error with a 400 status code.
"""

import os
import traceback

import pytz

from utils import api_return, setup_custom_logger

# Set the timezone to match CashBox
timezone = pytz.timezone("UTC")

# Set global variables from environment
try:
    HMAC_KEY = os.environ["hmac_key"]
    DEBUG = int(os.environ["debug"])
    REGION_NAME = os.environ["region"]
    BUCKET_NAME = os.environ["s3bucket"]
    USERAGENT = ("eventManager 1.0",)
    RETRY_COUNT = 3
    API_ENV = os.environ["api_env"]
    API_CREDS = os.environ["api_key"].split(":")
    API_BASE = os.environ["api_base"]
    API_VERSION = os.environ["api_version"]
except KeyError as e:
    # No logger has been defined yet so print the traceback and return an error
    traceback.print_exc()

    api_return(
        "400",
        return_string=f"Config error: Missing key {str(e)}",
    )


# Setup Logging - logging to CloudWatch Log
logger = setup_custom_logger("root")
