# Architecture Documentation

## System Architecture

This document provides detailed architectural information about the Vindicia Webhook Receiver system.

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [Component Details](#component-details)
- [Data Flow](#data-flow)
- [Security Model](#security-model)
- [Storage Strategy](#storage-strategy)
- [Event Processing Pipeline](#event-processing-pipeline)
- [Error Handling](#error-handling)
- [Scalability Considerations](#scalability-considerations)

## High-Level Architecture

### AWS Infrastructure

```
┌─────────────────────────────────────────────────────────────────┐
│                        AWS Cloud                                 │
│                                                                   │
│  ┌──────────────────┐         ┌─────────────────────────────┐   │
│  │  API Gateway     │         │   CloudWatch Logs           │   │
│  │  REST Endpoint   │-------->│   - Monitoring              │   │
│  │  /event_manager  │         │   - Debugging               │   │
│  └────────┬─────────┘         └─────────────────────────────┘   │
│           │                                                       │
│           │ Invoke                                                │
│           ↓                                                       │
│  ┌───────────────────────────────────────────┐                   │
│  │   Lambda Function                         │                   │
│  │   - Runtime: Python 3.9                   │                   │
│  │   - Memory: Default (128MB-3008MB)        │                   │
│  │   - Timeout: Default (6 seconds)          │                   │
│  │   - Environment Variables: Injected       │                   │
│  └───────────────┬───────────────────────────┘                   │
│                  │                                                │
│                  │ Write Objects                                  │
│                  ↓                                                │
│  ┌─────────────────────────────────┐                             │
│  │   S3 Bucket                     │                             │
│  │   - Hierarchical organization   │                             │
│  │   - JSON object storage         │                             │
│  │   - Versioning (optional)       │                             │
│  └─────────────────────────────────┘                             │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
         ↑                                    |
         |                                    |
         | HTTPS POST                         | REST API Calls
         | (with HMAC)                        | (optional)
         |                                    ↓
┌────────────────────┐            ┌────────────────────┐
│  Vindicia          │            │  Vindicia          │
│  Push Notifications│            │  REST/SOAP API     │
└────────────────────┘            └────────────────────┘
```

### Application Layer Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     handler.py                                │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  vin_event(event, context)                             │  │
│  │  - Entry point from AWS Lambda                         │  │
│  │  - Handles local testing mode                          │  │
│  │  - Computes HMAC for local invocations                 │  │
│  └───────────────────┬────────────────────────────────────┘  │
└────────────────────────┼───────────────────────────────────────┘
                         │
                         │ Delegates
                         ↓
┌──────────────────────────────────────────────────────────────┐
│                   eventManager.py                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  event_manager(event)                                  │  │
│  │  1. Parse message header                               │  │
│  │  2. Validate HMAC signature                            │  │
│  │  3. Determine class ID (merchant/VID)                  │  │
│  │  4. Store message to S3                                │  │
│  │  5. Execute event-specific logic                       │  │
│  └───────────────────┬────────────────────────────────────┘  │
└────────────────────────┼───────────────────────────────────────┘
                         │
                         │ Uses utilities
                         ↓
┌──────────────────────────────────────────────────────────────┐
│                      utils.py                                 │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  • validate() - HMAC validation                        │  │
│  │  • storeMessage() - S3 operations                      │  │
│  │  • get_modification_tx() - Fetch transactions          │  │
│  │  • get_subscription() - Fetch AutoBill updates         │  │
│  │  • api_return() - Response formatting                  │  │
│  │  • ct_compare() - Constant-time comparison             │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                         ↑
                         │ Configuration
                         │
┌──────────────────────────────────────────────────────────────┐
│                      config.py                                │
│  • Load environment variables                                 │
│  • Initialize logger                                          │
│  • Set timezone (UTC)                                         │
│  • Define global constants                                    │
└──────────────────────────────────────────────────────────────┘
```

## Component Details

### handler.py - Lambda Entry Point

**Purpose**: Serve as the AWS Lambda handler function and support local testing.

**Key Responsibilities**:
- Accept Lambda invocation events
- Support local testing by detecting missing HTTP headers
- Compute HMAC signatures for local test payloads
- Delegate to `event_manager()` for business logic
- Return properly formatted API Gateway responses

**Design Decisions**:
- Separate handler from business logic for testability
- Auto-generate signatures in local mode for developer convenience
- Use message_id from payload for consistent logging

### eventManager.py - Business Logic Core

**Purpose**: Orchestrate event processing workflow and implement business rules.

**Key Responsibilities**:
- Parse and validate incoming webhook structure
- Authenticate using HMAC signatures
- Extract appropriate identifiers (merchantId or VID) based on event type
- Store events to S3
- Trigger follow-up actions based on event type
- Handle edge cases in Vindicia message structure

**Design Decisions**:

1. **Special Case Handling**: Different event types have different structures:
   - `autobills/modify`: Contains autobill object within content
   - `accounts/data change`: Contains account object within content
   - `invoices/*`: Invoice ID in header instead of content
   - Others: Merchant ID directly in content

2. **Follow-up Action Logic**:
   - AutoBill modifications may generate pro-rated transactions
   - Successful transactions may change billing state
   - Failed transactions may trigger retry state changes
   - Only fetch additional data when billing state actually changes

3. **Error Recovery**:
   - Store original message first, then attempt follow-up actions
   - Return 202 (Accepted) for non-critical follow-up failures
   - Return 200 (OK) only when all operations succeed

### utils.py - Shared Utilities

**Purpose**: Provide reusable functions for common operations.

**Key Functions**:

#### `validate(message_id, body, sig)`
- Computes HMAC-SHA256 of request body using configured key
- Base64-encodes the hash for comparison
- Uses constant-time comparison to prevent timing attacks
- Supports "TEST" signature for local development

#### `storeMessage(class_id, message)`
- Organizes messages by date, class, and event type
- Formats: `YYYYMMDD/class_name/event_name/message_id`
- Handles multiple timestamp formats
- Stores structured JSON with metadata and content

#### `get_modification_tx(message_id, autobill, event_timestamp)`
- Fetches transactions for an AutoBill
- Searches within 300-second window of event
- Identifies modification transactions by `vin:type=modify` metadata
- Returns matching transaction or None

#### `get_subscription(id)`
- Fetches updated AutoBill when billing state changes
- Wraps as `autobills/state change` event
- Stores the updated subscription data

#### `ct_compare(a, b)`
- Constant-time string comparison
- Prevents timing attacks during HMAC validation
- XOR-based implementation

### config.py - Configuration Management

**Purpose**: Centralize configuration and initialization.

**Key Responsibilities**:
- Load and validate environment variables
- Initialize global logger
- Set timezone to UTC (matching Vindicia)
- Define constants (RETRY_COUNT, etc.)

**Design Decisions**:
- Fail fast if required environment variables missing
- Single logger instance for consistent formatting
- UTC timezone to match Vindicia event timestamps

## Data Flow

### Successful Event Processing

```
1. Vindicia sends webhook
   POST https://<api-gateway>/event_manager
   Header: X-Webhook-Signature: <base64-hmac>
   Body: { "header": {...}, "content": {...} }
   
2. API Gateway receives request
   - Routes to Lambda function
   - Passes headers and body
   
3. handler.vin_event() invoked
   - Extracts event structure
   - Calls event_manager()
   
4. event_manager() processes
   - Parses header: message_id, class_name, event_name
   - Validates HMAC signature
   - Determines class_id (merchant ID or VID)
   
5. storeMessage() called
   - Formats S3 key: YYYYMMDD/class_name/event_name/message_id
   - Stores JSON object to S3
   - Returns success (200)
   
6. Event-specific logic executes
   - For autobills/modify: Fetch modification transaction
   - For transactions/attempt succeeded: Fetch updated AutoBill
   - For transactions/attempt failed: Fetch updated AutoBill
   - Others: No additional action
   
7. api_return() formats response
   - Status code: 200, 202, or error code
   - Body: JSON with message_id and status message
   
8. API Gateway returns response to Vindicia
   - Vindicia marks webhook as delivered
```

### Error Scenarios

#### Invalid Signature (403)

```
1. Vindicia sends webhook with invalid/mismatched HMAC
2. handler.vin_event() → event_manager()
3. validate() computes expected signature
4. ct_compare() returns False (signatures don't match)
5. api_return("403", return_string="Signature does not match")
6. Vindicia receives 403 and retries later
```

#### Storage Failure (411)

```
1. Event validated successfully
2. storeMessage() attempts S3 write
3. boto3 raises ClientError (bucket doesn't exist, no permissions, etc.)
4. Exception caught and logged
5. api_return("411", return_string="Error storing message")
6. Vindicia receives 411 and retries later
```

#### Missing Message Fields (400)

```
1. Webhook body missing required header fields
2. event_manager() tries to parse header
3. KeyError exception raised
4. Exception caught with details
5. api_return("400", return_string="Cannot parse message header")
6. Vindicia receives 400 (permanent failure, won't retry)
```

## Security Model

### HMAC-SHA256 Signature Validation

**Process**:
1. Vindicia computes: `HMAC-SHA256(secret_key, JSON_body)`
2. Result is Base64-encoded and sent in `X-Webhook-Signature` header
3. Lambda receives webhook and extracts signature
4. Lambda computes: `HMAC-SHA256(configured_key, received_body)`
5. Lambda Base64-encodes its computed hash
6. Constant-time comparison between received and computed signatures

**Security Properties**:
- **Authentication**: Proves webhook came from holder of secret key
- **Integrity**: Detects any modification to payload
- **Constant-time**: Prevents timing attacks through XOR-based comparison
- **Replay protection**: Combined with message_id deduplication (if implemented)

**Key Management**:
- Secret key stored in Lambda environment variables
- Not logged or exposed in responses
- Should be rotated periodically via Vindicia portal

### IAM Role Permissions

Lambda execution role requires:

```yaml
Effect: Allow
Actions:
  - s3:PutObject
  - s3:PutObjectAcl
  - logs:CreateLogGroup
  - logs:CreateLogStream
  - logs:PutLogEvents
Resources:
  - arn:aws:s3:::bucket-name/*
  - arn:aws:logs:region:account:log-group:/aws/lambda/*
```

**Principle of Least Privilege**:
- Only S3 write permissions (no read/delete)
- Scoped to specific bucket
- CloudWatch logs for observability

## Storage Strategy

### S3 Organization

```
s3://bucket-name/
├── 20240115/                          # Date-based partitioning
│   ├── autobills/
│   │   ├── start/
│   │   │   ├── msg-001
│   │   │   └── msg-002
│   │   ├── stop/
│   │   │   └── msg-003
│   │   └── modify/
│   │       └── msg-004
│   └── transactions/
│       ├── attempt succeeded/
│       │   ├── msg-005
│       │   └── msg-006
│       └── attempt failed/
│           └── msg-007
└── 20240116/
    └── ...
```

**Benefits**:
- **Queryability**: Easy to find events by date
- **Lifecycle Management**: Apply retention policies by date prefix
- **Performance**: S3 list operations efficient within date partitions
- **Analytics**: Can be queried by AWS Athena with date partitioning

### Object Structure

Each S3 object contains:

```json
{
  "message_id": "unique-id-from-vindicia",
  "class_id": "MERCHANT-ID-123 or VID",
  "class_name": "transactions",
  "event_name": "attempt succeeded",
  "merchant_vid": "merchant-identifier",
  "event_timestamp": "2024-01-15T10:30:45.123",
  "soap_version": "27.0",
  "notification": {
    ... // Full Vindicia event object
  }
}
```

**Design Rationale**:
- **Metadata duplication**: Key fields extracted for easy querying
- **Full payload preservation**: Complete notification stored for debugging
- **Flat structure**: Easy to parse and query
- **JSON format**: Human-readable, tooling-friendly

## Event Processing Pipeline

### Decision Tree for Event Processing

```
┌─────────────────────────┐
│   Webhook Received      │
└────────┬────────────────┘
         │
         ↓
┌─────────────────────────┐
│  Validate Signature     │
│  ├─ Valid → Continue    │
│  └─ Invalid → 403       │
└────────┬────────────────┘
         │
         ↓
┌─────────────────────────┐
│  Parse Header           │
│  ├─ Success → Continue  │
│  └─ Error → 406         │
└────────┬────────────────┘
         │
         ↓
┌─────────────────────────┐
│  Extract Class ID       │
│  ├─ Found → Continue    │
│  └─ Missing → 400       │
└────────┬────────────────┘
         │
         ↓
┌─────────────────────────┐
│  Store to S3            │
│  ├─ Success → Continue  │
│  └─ Error → 411         │
└────────┬────────────────┘
         │
         ↓
┌─────────────────────────────────────────────┐
│  Event-Specific Processing                  │
│  ├─ autobills/modify                        │
│  │   └─ Fetch modification transaction      │
│  ├─ transactions/attempt succeeded          │
│  │   └─ Fetch updated AutoBill              │
│  ├─ transactions/attempt failed             │
│  │   └─ Fetch updated AutoBill              │
│  └─ Others                                  │
│      └─ No additional action                │
└────────┬────────────────────────────────────┘
         │
         ↓
┌─────────────────────────┐
│  Return Response        │
│  ├─ 200: Success        │
│  ├─ 202: Follow-up issue│
│  └─ 206: Partial success│
└─────────────────────────┘
```

### AutoBill Modify Processing Details

```
autobills/modify event received
│
├─ Store original event
│
└─ Fetch transactions for AutoBill
    │
    ├─ Find transaction within 300s of event
    │  with metadata vin:type=modify
    │
    ├─ If found:
    │  ├─ Extract transaction details
    │  ├─ Create new message structure
    │  │  ├─ header.class_name = "transactions"
    │  │  ├─ header.event_name = "modify"
    │  │  └─ content = transaction object
    │  ├─ Store as transactions/modify event
    │  └─ Return 200
    │
    └─ If not found:
       └─ Return 202 (Warning: no modification tx)
```

### Transaction Processing Logic

```
transactions/* event received
│
├─ Check if generated by AutoBill (autoBillCycle present)
│
├─ If attempt succeeded:
│  ├─ autoBillCycle == 0 (initial billing)
│  │  └─ Fetch AutoBill (status changed to Active)
│  │
│  └─ retryNumber > 0 (successful retry)
│     └─ Fetch AutoBill (billingState → Good Standing)
│
└─ If attempt failed:
   ├─ autoBillCycle > 0 AND retryNumber == 0
   │  └─ Fetch AutoBill (first decline, state → In Retry)
   │
   └─ retryNumber >= RETRY_COUNT
      └─ Fetch AutoBill (last retry, final state)
```

## Error Handling

### Error Response Strategy

| Scenario | Code | Retry? | Rationale |
|:---------|:-----|:-------|:----------|
| Signature mismatch | 403 | Yes | Could be transient network issue |
| Cannot parse header | 406 | No | Permanent structural problem |
| Missing fields | 400 | No | Malformed request |
| Storage failure | 411 | Yes | S3 may have temporary issues |
| Follow-up fetch issue | 202 | No | Original event stored successfully |

### Logging Strategy

**Log Levels**:
- **ERROR**: Failures that prevent normal operation
- **WARNING**: Issues that don't prevent operation (e.g., no modification tx found)
- **INFO**: Normal operational events (received, stored, fetched)
- **DEBUG**: Detailed information for troubleshooting (signatures, full payloads)

**Log Format**:
```
timestamp,ms LEVEL module:line - message
```

**Context in Logs**:
- Always include `message_id` for traceability
- Include `class_name/event_name` for context
- Include relevant IDs (merchantAutoBillId, VID, etc.)

### Exception Handling Patterns

```python
# Pattern 1: Catch specific exceptions, log, return error
try:
    operation()
except SpecificError as e:
    logger.exception("Context: %s", details)
    return api_return("4XX", return_string="Error message")

# Pattern 2: Multiple specific handlers
try:
    operation()
except KeyError as e:
    # Handle missing data
    return api_return("400", ...)
except BotoCoreError as e:
    # Handle AWS errors
    return api_return("411", ...)

# Pattern 3: Continue on non-critical errors
response = critical_operation()
if response.success:
    try:
        optional_operation()
    except Exception as e:
        logger.warning("Non-critical error: %s", e)
        # Continue anyway
return api_return("200", ...)
```

## Scalability Considerations

### Lambda Scaling

**Concurrency**:
- Lambda automatically scales to handle concurrent webhook deliveries
- Default: 1000 concurrent executions per region
- Each execution processes one webhook independently
- No shared state between executions

**Performance**:
- Cold start: ~200-500ms (Python 3.9 with dependencies)
- Warm execution: ~50-200ms typical
- S3 write: ~50-100ms
- API calls (if needed): ~200-500ms

**Cost Optimization**:
- Provisioned concurrency not needed (webhooks not latency-sensitive)
- Use minimum memory allocation sufficient for workload
- S3 storage is cost-effective for historical event data

### S3 Scalability

**Performance**:
- S3 automatically scales to handle request volume
- 3,500 PUT/POST requests per second per prefix
- Date-based prefixing distributes load across partitions

**Storage**:
- Unlimited total storage
- Each webhook ~1-10KB typically
- 1 million webhooks/day = ~5GB/day = ~150GB/month
- Use S3 Lifecycle policies to archive or delete old data

### Bottlenecks & Mitigations

**Potential Bottleneck**: Vindicia API rate limits when fetching related objects

**Mitigation**:
- Only fetch when billing state changes (selective)
- Consider implementing exponential backoff
- Cache frequently accessed data (if needed)
- Use REST API instead of SOAP where possible (better performance)

**Potential Bottleneck**: Lambda timeout (default 6s, max 15 minutes)

**Mitigation**:
- Most webhooks process in <1 second
- Follow-up API calls add 200-500ms
- Consider async processing for complex follow-ups (SQS + separate function)

### Monitoring & Alerting

**Key Metrics**:
- Lambda invocations (rate)
- Lambda errors (count & rate)
- Lambda duration (p50, p95, p99)
- Lambda throttles (should be zero)
- S3 PUT operations (rate)
- S3 PUT errors (should be near zero)

**Recommended Alarms**:
- Lambda error rate > 1% (investigate)
- Lambda duration > 5s (may indicate timeout risk)
- S3 PUT errors > 0 (storage issue)
- No invocations for extended period (webhook delivery problem)

### Future Enhancements

**Potential Improvements**:

1. **Deduplication**: Track message_ids in DynamoDB to prevent reprocessing
2. **Dead Letter Queue**: Capture failed events for manual review
3. **Async Processing**: Use SQS for follow-up actions to reduce webhook latency
4. **Caching**: Cache AutoBill/Transaction data in DynamoDB for faster follow-up lookups
5. **Metrics**: Emit custom CloudWatch metrics for business events
6. **Alerting**: SNS notifications for specific event types or error patterns
7. **Testing**: Automated integration tests with mocked Vindicia API
8. **Observability**: X-Ray tracing for distributed debugging
