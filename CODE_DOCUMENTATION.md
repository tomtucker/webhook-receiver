# Code Documentation

This document provides detailed documentation of the codebase, including function signatures, algorithms, and implementation details.

## Table of Contents

- [Module Overview](#module-overview)
- [handler.py](#handlerpy)
- [eventManager.py](#eventmanagerpy)
- [utils.py](#utilspy)
- [config.py](#configpy)
- [Algorithms & Patterns](#algorithms--patterns)
- [Testing Guide](#testing-guide)

## Module Overview

| Module | Lines | Purpose | Dependencies |
|:-------|:------|:--------|:-------------|
| `handler.py` | ~100 | Lambda entry point | eventManager, utils, config |
| `eventManager.py` | ~400 | Event processing logic | utils, config |
| `utils.py` | ~650 | Utility functions | config, boto3, requests |
| `config.py` | ~50 | Configuration setup | os, pytz |

## handler.py

### Main Entry Point

```python
def vin_event(event: dict, context: LambdaContext) -> dict
```

**Purpose**: AWS Lambda handler function that receives API Gateway events and orchestrates webhook processing.

**Parameters**:
- `event` (dict): AWS Lambda event object containing:
  ```python
  {
      "headers": {
          "X-Webhook-Signature": "base64-encoded-hmac",
          "Content-Type": "application/json",
          ...
      },
      "body": "json-string-of-webhook-payload"
  }
  ```
- `context` (LambdaContext): AWS Lambda context object (unused in current implementation)

**Returns**:
- dict: API Gateway-compatible response:
  ```python
  {
      "statusCode": 200,  # HTTP status code
      "body": '{"message_id": "...", "return_string": "..."}'
  }
  ```

**Behavior**:

1. **Normal AWS Lambda execution**:
   - Event contains `headers` key from API Gateway
   - Passes directly to `event_manager()`

2. **Local testing mode** (no headers):
   - Detects missing `headers` key
   - Extracts `message_id` from payload
   - Computes HMAC-SHA256 signature of body
   - Creates synthetic API Gateway event structure
   - Logs warning about local mode

**Error Handling**:
- KeyError on missing `message_id`: Returns 406 with error message
- TypeError on invalid structure: Returns 406 with error message

**Example Usage**:

```python
# AWS Lambda invocation (normal)
event = {
    "headers": {"X-Webhook-Signature": "abc123..."},
    "body": '{"header": {...}, "content": {...}}'
}
response = vin_event(event, context)

# Local testing (serverless invoke local)
event = {
    "header": {"message_id": "test-123", ...},
    "content": {...}
}
response = vin_event(event, None)  # Auto-generates signature
```

## eventManager.py

### Main Event Processing Function

```python
def event_manager(event: dict) -> dict
```

**Purpose**: Core business logic for processing Vindicia webhook events.

**Parameters**:
- `event` (dict): Event structure with `headers` and `body` keys (from handler)

**Returns**:
- dict: API response with status code and details

**Processing Steps**:

1. **Parse Message Body**:
   ```python
   message = json.loads(event["body"])
   class_name = message["header"]["class_name"]
   event_name = message["header"]["event_name"]
   message_id = message["header"]["message_id"]
   event_timestamp = message["header"]["event_timestamp"]
   ```

2. **Validate HMAC Signature**:
   ```python
   if validate(message_id, message, event["headers"]["X-Webhook-Signature"]):
       # Continue processing
   else:
       return api_return("403", ...)
   ```

3. **Extract Class ID**:
   - Determines which identifier to use (merchant ID or VID)
   - Different logic per class_name:
     - `autobills/modify`: ID in `message["content"]["autobill"]["merchantAutoBillId"]`
     - `accounts/data change`: ID in `message["content"]["account"]["merchantAccountId"]`
     - `invoices/*`: ID in `message["header"]["invoice_id"]`
     - Others: ID in `message["content"][classId_field]`
   - Falls back to VID if merchant ID not found

4. **Store Message**:
   ```python
   response = storeMessage(class_id, message)
   if int(response["statusCode"]) > 299:
       return response  # Storage failed, exit
   ```

5. **Event-Specific Processing**:
   ```python
   if class_name == "autobills" and event_name == "modify":
       transaction = get_modification_tx(message_id, autobill, event_timestamp)
       if transaction:
           # Store as transactions/modify event
   
   elif class_name == "transactions" and event_name == "attempt succeeded":
       if autoBillCycle == 0 or retryNumber > 0:
           return get_subscription(message)
   
   elif class_name == "transactions" and event_name == "attempt failed":
       if autoBillCycle > 0 and (retryNumber == 0 or retryNumber >= RETRY_COUNT):
           return get_subscription(message)
   ```

6. **Return Success**:
   ```python
   return api_return("200", return_string="OK", message_id=message_id)
   ```

**Error Paths**:

- **406**: Cannot parse message header (missing required fields)
- **403**: Signature validation failed
- **400**: Cannot determine class ID or missing merchant identifier
- **Storage errors (409-411)**: Propagated from `storeMessage()`

### Class ID Mapping

```python
classIds = {
    "accounts": "merchantAccountId",
    "adjustments": "merchantRefundId",
    "autobills": "merchantAutoBillId",
    "transactions": "merchantTransactionId",
    "entitlement": "merchantAccountId",
    "invoices": "invoice_id",
    "payment methods": "merchantPaymentMethodId",
}
```

This mapping defines where to find the primary identifier for each object type in Vindicia messages.

## utils.py

### HMAC Validation

```python
def validate(message_id: str, body: dict, sig: str) -> bool
```

**Purpose**: Validate webhook authenticity using HMAC-SHA256 signature.

**Parameters**:
- `message_id` (str): Message ID for logging
- `body` (dict): Parsed JSON message body
- `sig` (str): Base64-encoded HMAC signature from request header

**Returns**:
- bool: True if signature matches, False otherwise

**Algorithm**:

1. Convert received signature to bytes
2. Serialize body to JSON (no whitespace: `separators=(",", ":")`)
3. Compute HMAC-SHA256:
   ```python
   body_hash = base64.b64encode(
       hmac.new(
           config.HMAC_KEY.encode('utf-8'),
           json.dumps(body, separators=(',', ':')).encode('utf-8'),
           hashlib.sha256
       ).digest()
   )
   ```
4. Compare using constant-time comparison: `ct_compare(str(body_hash), str(sig))`

**Special Cases**:
- Signature = "TEST": Returns True (for local testing)
- Mismatched lengths: Returns False immediately
- Debug level > 2: Logs full body for troubleshooting

**Security Notes**:
- Uses constant-time comparison to prevent timing attacks
- Compacts JSON to match Vindicia's serialization
- Does not log signature values at normal log levels

---

### Constant-Time String Comparison

```python
def ct_compare(a: str, b: str) -> bool
```

**Purpose**: Compare two strings in constant time to prevent timing attacks.

**Parameters**:
- `a` (str): First string
- `b` (str): Second string

**Returns**:
- bool: True if strings are equal, False otherwise

**Algorithm**:

```python
if len(a) != len(b):
    return False  # Fast path for different lengths

result = 0
for ch_a, ch_b in zip(a, b):
    result |= ord(ch_a) ^ ord(ch_b)

return result == 0
```

**How It Works**:
1. XOR each character pair: same chars = 0, different = non-zero
2. OR all XOR results: any difference makes result non-zero
3. Check if result is 0 (all characters matched)

**Time Complexity**: O(n) where n = length of strings (constant regardless of where differences occur)

---

### S3 Message Storage

```python
def storeMessage(class_id: str, message: dict) -> dict
```

**Purpose**: Store webhook message to S3 with hierarchical organization.

**Parameters**:
- `class_id` (str): Merchant identifier or Vindicia ID
- `message` (dict): Full webhook message with header and content

**Returns**:
- dict: API response with status code and message

**Process**:

1. **Initialize S3 client**:
   ```python
   s3 = boto3.resource("s3", config.REGION_NAME)
   ```

2. **Build item structure**:
   ```python
   Item = {
       "message_id": message["header"]["message_id"],
       "class_id": class_id,
       "class_name": message["header"]["class_name"],
       "event_name": message["header"]["event_name"],
       "merchant_vid": message["header"]["merchant_vid"],
       "event_timestamp": message["header"]["event_timestamp"],
       "soap_version": message["header"]["soap_version"],
       "notification": message["content"]
   }
   ```

3. **Parse timestamp and build S3 key**:
   ```python
   timestamp_formats = [
       "%Y-%m-%dT%H:%M:%S.%f",  # ISO 8601 with microseconds
       "%Y-%m-%dT%H:%M:%S",      # ISO 8601 without microseconds
       "%Y-%m-%d %H:%M:%S"       # Space-separated format
   ]
   timestamp = parse_with_formats(event_timestamp, timestamp_formats)
   
   path = (timestamp.strftime("%Y%m%d") + "/" +
           class_name + "/" +
           event_name + "/")
   file_name = path + message_id
   ```

4. **Write to S3**:
   ```python
   s3.Bucket(config.BUCKET_NAME).put_object(
       Key=file_name,
       Body=json.dumps(Item, default=json_serial)
   )
   ```

**Error Handling**:
- **409**: Error setting S3 resource
- **410**: Cannot extract message components (KeyError)
- **411**: S3 put_object failure or timestamp parsing error

**Example S3 Path**:
```
s3://vin.eventmanager/20240115/transactions/attempt succeeded/550e8400-e29b-41d4-a716-446655440000
```

---

### Get Modification Transaction

```python
def get_modification_tx(message_id: str, autobill: dict, event_timestamp: str) -> dict | None
```

**Purpose**: Fetch the transaction generated by an AutoBill modification (pro-rated charges).

**Parameters**:
- `message_id` (str): Message ID for logging
- `autobill` (dict): AutoBill object from webhook
- `event_timestamp` (str): RFC 3339 timestamp of modification event

**Returns**:
- dict: Transaction object if found
- None: No modification transaction found within time window

**Algorithm**:

1. **Extract AutoBill VID and parse timestamp**:
   ```python
   vid = autobill["VID"]
   event_timestamp = config.timezone.localize(
       datetime.strptime(event_timestamp, "%Y-%m-%dT%H:%M:%S.%f")
   )
   ```

2. **Fetch all transactions for AutoBill**:
   ```python
   fetchParameters = {"srd": "", "autobill": {"VID": vid}}
   response = vin_proxy("Transaction.fetchByAutobill", fetchParameters)
   ```

3. **Search for modification transaction**:
   ```python
   for transaction in response["transactions"]:
       diff = event_timestamp - transaction["timestamp"]
       if diff.total_seconds() < 300:  # Within 5 minutes
           for nameValue in transaction["nameValues"]:
               if nameValue["name"] == "vin:type" and nameValue["value"] == "modify":
                   return transaction
   ```

**Time Window**: 300 seconds (5 minutes) - modification transactions occur immediately after AutoBill.modify()

**Metadata Identifier**: Looks for `nameValues` entry with `name="vin:type"` and implicit value of "modify"

**Use Case**: AutoBill modifications with product additions may generate pro-rated charges. This function retrieves that transaction for storage as a `transactions/modify` event.

---

### Get Updated Subscription

```python
def get_subscription(message: dict) -> dict
```

**Purpose**: Fetch updated AutoBill data when billing state changes due to transaction events.

**Parameters**:
- `message` (dict): Original transaction webhook message

**Returns**:
- dict: API response (202 with details)

**Process**:

1. **Extract AutoBill VID from transaction**:
   ```python
   fetchParameters = {"srd": "", "vid": message["content"]["autobillVID"]}
   ```

2. **Fetch AutoBill via SOAP API**:
   ```python
   response = vin_proxy("AutoBill.fetchByVid", fetchParameters)
   ```

3. **Transform message structure**:
   ```python
   merchantAutoBillId = response["autobill"]["merchantAutoBillId"]
   message["content"] = response["autobill"]
   message["header"]["class_name"] = "autobills"
   message["header"]["event_name"] = "state change"
   ```

4. **Store transformed message**:
   ```python
   response = storeMessage(merchantAutoBillId, message)
   ```

**Use Case**:
- Initial billing success → AutoBill status changes to Active
- Retry success → AutoBill billingState changes to Good Standing
- First decline → AutoBill billingState changes to In Retry
- Final retry failure → AutoBill billingState changes to final failure state

**Note**: Always returns 202 (Accepted) since this is a follow-up action to the original transaction storage.

---

### API Response Formatter

```python
def api_return(returnCode: str, **body) -> dict
```

**Purpose**: Format responses for API Gateway in required structure.

**Parameters**:
- `returnCode` (str): HTTP status code
- `**body`: Arbitrary keyword arguments for response body

**Returns**:
- dict: API Gateway response object

**Output Format**:
```python
{
    "statusCode": "200",
    "body": '{"return_string":"OK","message_id":"123"}'
}
```

**JSON Serialization**:
- Uses `json_serial()` for custom type handling (datetime, Decimal, sets)
- Compact JSON: `separators=(',', ':')`

**Usage Examples**:
```python
api_return("200", return_string="OK", message_id="abc-123")
api_return("403", return_string="Signature mismatch")
api_return("400", return_string="Missing field", field="merchantId")
```

---

### JSON Serializer for Special Types

```python
def json_serial(obj: Any) -> str | list
```

**Purpose**: Handle non-standard types during JSON serialization.

**Supported Types**:
- `datetime` / `date`: Converts to ISO 8601 string
- `decimal.Decimal`: Converts to string
- `set`: Converts to tuple
- Other iterables: Converts to list

**Usage**:
```python
json.dumps(data, default=json_serial)
```

**Example**:
```python
data = {
    "timestamp": datetime.now(),
    "amount": Decimal("29.99"),
    "tags": {"premium", "monthly"}
}
# Serializes to: {"timestamp": "2024-01-15T10:30:45", "amount": "29.99", "tags": ["premium", "monthly"]}
```

## config.py

### Module Purpose

Centralizes configuration loading and initialization. Executes on import to set up global state.

### Global Variables

```python
# Timezone
timezone = pytz.timezone("UTC")

# Environment Variables
HMAC_KEY = os.environ["hmac_key"]          # Secret key for HMAC validation
DEBUG = int(os.environ["debug"])            # Debug level (0-5)
REGION_NAME = os.environ["region"]          # AWS region
BUCKET_NAME = os.environ["s3bucket"]        # S3 bucket name
API_ENV = os.environ["api_env"]             # Vindicia environment (Staging/Production)
API_CREDS = os.environ["api_key"].split(":") # [username, password]
API_BASE = os.environ["api_base"]           # REST API base URL
API_VERSION = os.environ["api_version"]     # SOAP API version

# Constants
USERAGENT = "eventManager 1.0"
RETRY_COUNT = 3  # Max retry attempts for failed transactions
```

### Logger Setup

```python
logger = setup_custom_logger("root")
```

**Logger Configuration**:
- Name: "root" (global logger)
- Format: `%(asctime)s,%(msecs)d %(levelname)s %(module)s:%(lineno)d - %(message)s`
- Output: StreamHandler (stdout/stderr → CloudWatch Logs in Lambda)
- Level: DEBUG if `DEBUG > 0`, else INFO

### Error Handling

If any required environment variable is missing:
1. Prints traceback to stdout
2. Calls `api_return("400", return_string="Config error: Missing key {key}")`
3. Does NOT raise exception (allows module to import)

**Note**: Lambda will fail on first invocation if config is invalid.

## Algorithms & Patterns

### 1. HMAC Signature Validation Pattern

**Problem**: Prevent timing attacks when comparing cryptographic signatures.

**Solution**: Constant-time comparison using XOR and OR operations.

```python
def validate_signature(received_sig, computed_sig):
    if len(received_sig) != len(computed_sig):
        return False
    
    result = 0
    for a, b in zip(received_sig, computed_sig):
        result |= ord(a) ^ ord(b)
    
    return result == 0
```

**Why It Works**:
- XOR returns 0 for matching characters, non-zero for differences
- Bitwise OR accumulates any differences
- Final check is O(1) comparison
- Execution time depends only on string length, not content

### 2. Flexible Timestamp Parsing

**Problem**: Vindicia may send timestamps in multiple formats.

**Solution**: Try multiple formats sequentially.

```python
timestamp_formats = [
    "%Y-%m-%dT%H:%M:%S.%f",  # With microseconds
    "%Y-%m-%dT%H:%M:%S",      # Without microseconds
    "%Y-%m-%d %H:%M:%S"       # Space-separated
]

timestamp = None
for fmt in timestamp_formats:
    try:
        timestamp = datetime.strptime(event_timestamp, fmt)
        break
    except ValueError:
        continue

if not timestamp:
    raise ValueError("Invalid timestamp format")
```

### 3. Hierarchical S3 Key Generation

**Pattern**: Date-based partitioning for efficient querying and lifecycle management.

```python
def generate_s3_key(timestamp, class_name, event_name, message_id):
    date_prefix = timestamp.strftime("%Y%m%d")
    return f"{date_prefix}/{class_name}/{event_name}/{message_id}"
```

**Benefits**:
- Chronological organization
- Easy to query by date range
- Efficient S3 list operations
- Supports lifecycle policies (e.g., archive to Glacier after 90 days)

### 4. Error Recovery Pattern

**Pattern**: Store first, fail later for non-critical operations.

```python
# Critical: Store original event
response = storeMessage(class_id, message)
if response["statusCode"] != "200":
    return response  # Fail if storage fails

# Non-critical: Fetch related data
try:
    related_data = fetch_related_data(message)
    if related_data:
        storeMessage(related_id, transformed_message)
        return api_return("200", return_string="OK with related data")
except Exception as e:
    logger.warning("Could not fetch related data: %s", e)
    # Don't fail the whole operation

return api_return("202", return_string="OK, related data not available")
```

**Rationale**:
- Webhook delivery is more important than follow-up actions
- 202 (Accepted) signals partial success
- Original event is never lost

### 5. Event-Driven State Machine

**Pattern**: Different processing paths based on event type and state.

```python
def process_event(class_name, event_name, content):
    # State 1: Store all events
    store(content)
    
    # State 2: Conditional processing
    if (class_name, event_name) == ("autobills", "modify"):
        handle_autobill_modification()
    
    elif (class_name, event_name) == ("transactions", "attempt succeeded"):
        if content["autoBillCycle"] == 0:
            handle_initial_billing()
        elif content["retryNumber"] > 0:
            handle_successful_retry()
    
    # State 3: Default success
    return success_response()
```

## Testing Guide

### Unit Testing Approach

**Test Isolation**: Mock external dependencies (boto3, requests, config).

```python
import unittest
from unittest.mock import Mock, patch
import eventManager

class TestEventManager(unittest.TestCase):
    
    @patch('eventManager.validate')
    @patch('eventManager.storeMessage')
    def test_successful_processing(self, mock_store, mock_validate):
        mock_validate.return_value = True
        mock_store.return_value = {"statusCode": "200"}
        
        event = {
            "headers": {"X-Webhook-Signature": "test-sig"},
            "body": json.dumps({
                "header": {
                    "message_id": "test-123",
                    "class_name": "transactions",
                    "event_name": "attempt succeeded",
                    "event_timestamp": "2024-01-15T10:30:45.123",
                    "merchant_vid": "MERCHANT-001",
                    "soap_version": "27.0"
                },
                "content": {
                    "merchantTransactionId": "TXN-001",
                    "amount": "29.99"
                }
            })
        }
        
        response = eventManager.event_manager(event)
        
        assert response["statusCode"] == "200"
        mock_validate.assert_called_once()
        mock_store.assert_called_once()
```

### Integration Testing

**Test End-to-End Flow**: Use real AWS resources in test environment.

```python
def test_webhook_integration():
    # Setup: Create test S3 bucket
    s3 = boto3.client('s3')
    s3.create_bucket(Bucket='test-webhook-bucket')
    
    # Execute: Invoke Lambda with test payload
    lambda_client = boto3.client('lambda')
    response = lambda_client.invoke(
        FunctionName='vin-webhook-dev-receiver',
        Payload=json.dumps(test_event)
    )
    
    # Verify: Check S3 for stored message
    result = s3.get_object(
        Bucket='test-webhook-bucket',
        Key='20240115/transactions/attempt succeeded/test-123'
    )
    
    assert result['Body'].read() is not None
    
    # Cleanup
    s3.delete_object(...)
    s3.delete_bucket(...)
```

### Local Testing with Serverless

```bash
# Test with specific JSON file
serverless invoke local --function receiver -p test/json/autobills_start.json

# Test with inline data
serverless invoke local --function receiver --data '{...}'

# View logs during local execution
DEBUG=1 serverless invoke local --function receiver -p test.json
```

### Creating Test Fixtures

**Minimal Valid Webhook**:
```json
{
  "header": {
    "message_id": "test-msg-001",
    "class_name": "transactions",
    "event_name": "attempt succeeded",
    "event_timestamp": "2024-01-15T10:30:45.123",
    "merchant_vid": "TEST-MERCHANT",
    "soap_version": "27.0"
  },
  "content": {
    "merchantTransactionId": "TXN-001",
    "autobillVID": "AB-001",
    "amount": "29.99",
    "autoBillCycle": 0,
    "retryNumber": 0
  }
}
```

### Test Coverage Goals

| Module | Target | Key Areas |
|:-------|:-------|:----------|
| handler.py | 90%+ | Normal/local mode, error handling |
| eventManager.py | 85%+ | All event types, error paths |
| utils.py | 80%+ | HMAC validation, S3 storage, constant-time comparison |
| config.py | 50%+ | Environment variable loading |

### Common Test Scenarios

1. **Valid webhook with signature**: Should return 200
2. **Invalid signature**: Should return 403
3. **Missing header fields**: Should return 406
4. **S3 storage failure**: Should return 411
5. **AutoBill modify with transaction**: Should store both events
6. **AutoBill modify without transaction**: Should return 202
7. **Initial billing success**: Should fetch and store AutoBill
8. **Transaction retry success**: Should fetch and store AutoBill
9. **Transaction first decline**: Should fetch and store AutoBill
10. **Local testing mode**: Should compute signature automatically
