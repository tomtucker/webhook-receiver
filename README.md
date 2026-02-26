# Webhook Receiver

A robust webhook receiver service for Vindicia/CashBox Subscribe push notifications with HMAC signature validation, deployed as an AWS Lambda function using the Serverless Framework.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [API Endpoints](#api-endpoints)
- [Event Processing Logic](#event-processing-logic)
- [Local Development & Testing](#local-development--testing)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## Overview

This service receives and processes webhook notifications from Vindicia/CashBox Subscribe. It validates incoming webhooks using HMAC-SHA256 signatures, stores event data in AWS S3, and performs intelligent event-driven actions such as fetching related subscription data when billing state changes occur.

### Key Capabilities

- **Security**: HMAC-SHA256 signature validation for all incoming webhooks
- **Storage**: Automatic organization and storage of events in S3 by date, class, and event type
- **Event Intelligence**: Detects billing state changes and fetches updated subscription data
- **Serverless Architecture**: Fully managed AWS Lambda deployment with API Gateway integration
- **Local Testing**: Support for local development and testing without AWS deployment

## Architecture

### Component Overview

```
┌─────────────────┐
│  Vindicia API   │
│  Push Events    │
└────────┬────────┘
         │ POST (with HMAC signature)
         ↓
┌─────────────────────────────┐
│   API Gateway               │
│   /event_manager endpoint   │
└────────┬────────────────────┘
         │
         ↓
┌──────────────────────────────────────────┐
│  AWS Lambda (handler.vin_event)          │
│  ┌────────────────────────────────────┐  │
│  │  1. Extract & validate signature   │  │
│  │  2. Parse event headers & body     │  │
│  └────────────────┬───────────────────┘  │
│                   ↓                       │
│  ┌────────────────────────────────────┐  │
│  │  eventManager.event_manager()      │  │
│  │  - Identify event type             │  │
│  │  - Extract merchant/class ID       │  │
│  │  - Store to S3                     │  │
│  │  - Trigger follow-up actions       │  │
│  └────────────────┬───────────────────┘  │
└───────────────────┼──────────────────────┘
                    │
        ┌───────────┴───────────┐
        ↓                       ↓
┌───────────────┐      ┌──────────────────┐
│   AWS S3      │      │  Subscribe API   │
│   Event Store │      │  (fetch related) │
└───────────────┘      └──────────────────┘
```

### File Structure & Responsibilities

- **`handler.py`**: AWS Lambda entry point, handles signature computation for local testing
- **`eventManager.py`**: Core business logic for event routing and processing
- **`config.py`**: Environment variable loading and logging configuration
- **`utils.py`**: Utility functions for HMAC validation, S3 storage, and API calls

## Features

### Security
- HMAC-SHA256 signature validation for secure webhook processing
- Constant-time comparison to prevent timing attacks
- Configurable secret key management

### Event Processing
- Support for all Vindicia Subscribe object types:
  - Accounts (accounts/data change)
  - AutoBills (autobills/start, stop, modify)
  - Transactions (transactions/attempt succeeded, attempt failed)
  - Adjustments (adjustments/refund)
  - Entitlements (entitlement/start, stop)
  - Invoices (invoices/payment received, pre-notification, status change)
  - Payment Methods
- Intelligent handling of AutoBill modifications with pro-rated transactions
- Automatic fetching of subscription state changes on billing events

### Storage & Organization
- S3 storage with hierarchical organization: `YYYYMMDD/class_name/event_name/message_id`
- Structured JSON format with metadata and notification content
- Automatic timestamp parsing with multiple format support

### Deployment & Development
- Serverless Framework for infrastructure-as-code
- Python 3.9 runtime
- Serverless plugins:
  - `serverless-python-requirements`: Automatic dependency packaging with Docker
  - `serverless-plugin-optimize`: Code optimization and minification
  - `serverless-s3-local`: Local S3 emulation for testing
- Local execution and testing without AWS deployment

### Monitoring & Debugging
- Configurable logging levels (0-5)
- CloudWatch Logs integration
- Detailed error messages with context (message_id, class_name, event_name)

## Prerequisites

### Required Software

- **AWS Account** with:
  - IAM user with Lambda, API Gateway, S3, and CloudWatch permissions
  - S3 bucket for storing webhook messages
- **AWS CLI** installed and configured (`aws configure`)
- **Serverless Framework** installed globally:
  ```bash
  npm install -g serverless
  ```
- **Python 3.9** (matches Lambda runtime)
- **Node.js** (for Serverless Framework)
- **Docker** (optional, for `serverless-python-requirements` plugin)

### Account Setup

1. Create an S3 bucket for message storage
2. Note your Vindicia API credentials (username and password)
3. Obtain the HMAC key from Vindicia for webhook signature validation

## Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd webhook-receiver
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Serverless plugins**:
   ```bash
   npm install
   ```

## Configuration

### Environment Variables

Configuration is managed through `serverless.yml`. Update the following variables in the `provider.environment` section:

| Variable     | Description                                                                                                                            | Example/Default       | Required |
|:-------------|:---------------------------------------------------------------------------------------------------------------------------------------|:----------------------|:---------|
| `debug`      | Debug output level (0-5). Higher values increase logging verbosity                                                                    | `0`                   | Yes      |
| `api_env`    | Vindicia environment (`Production` or `Staging`)                                                                                       | `Staging`             | Yes      |
| `api_base`   | Base URL for Vindicia REST API                                                                                                         | `https://api.staging.vindicia.com` | Yes |
| `api_version`| CashBox SOAP API version (must be quoted string)                                                                                       | `'27.0'`              | Yes      |
| `api_key`    | Vindicia API credentials in format `username:password`                                                                                 | `api_user:api_pass`   | Yes      |
| `hmac_key`   | 40-character HMAC key for webhook signature validation (provided by Vindicia)                                                          | `<secret_key>`        | Yes      |
| `region`     | AWS region for deployment                                                                                                              | `us-east-1`           | Yes      |
| `s3bucket`   | S3 bucket name for message storage. Update IAM role statements to grant access                                                         | `vin.eventmanager`    | Yes      |

### IAM Permissions

Update the `provider.iam.role.statements` section in `serverless.yml` to match your S3 bucket:

```yaml
iam:
  role:
    statements:
    - Effect: "Allow"
      Action:
      - "s3:*"
      Resource: { "Fn::Join": ["", ["arn:aws:s3:::YOUR-BUCKET-NAME", "/*" ] ] }
```

## Deployment

### Deploy to AWS

Deploy to your AWS account:

```bash
serverless deploy
```

After successful deployment, note the API endpoint URL from the output:

```
endpoints:
  POST - https://xxxxxxxxxx.execute-api.us-east-1.amazonaws.com/dev/event_manager
```

### Configure Vindicia Webhook

1. Log into your Vindicia CashBox environment
2. Navigate to Webhooks/Push Notifications configuration
3. Set the endpoint URL to the deployed API Gateway endpoint
4. Ensure the HMAC key matches your configuration

### Deploy Specific Function

To deploy only the function code (faster than full deployment):

```bash
serverless deploy function -f receiver
```

### Remove Deployment

To remove all AWS resources:

```bash
serverless remove
```

## API Endpoints

### POST /event_manager

Receives Vindicia push notification webhooks.

#### Request Headers

| Header                   | Description                                       | Required |
|:-------------------------|:--------------------------------------------------|:---------|
| `X-Webhook-Signature`    | Base64-encoded HMAC-SHA256 signature of the body  | Yes      |
| `Content-Type`           | `application/json`                                | Yes      |

#### Request Body

JSON payload following Vindicia Subscribe push notification structure:

```json
{
  "header": {
    "message_id": "unique-message-id",
    "class_name": "transactions",
    "event_name": "attempt succeeded",
    "event_timestamp": "2024-01-15T10:30:45.123",
    "merchant_vid": "merchant_identifier",
    "soap_version": "27.0"
  },
  "content": {
    "merchantTransactionId": "TXN-12345",
    "autobillVID": "AB-67890",
    "amount": "29.99",
    ...
  }
}
```

#### Response Codes

| Status Code | Meaning                                                                      |
|:------------|:-----------------------------------------------------------------------------|
| `200`       | Event processed successfully                                                 |
| `202`       | Event stored but follow-up action had issues (non-critical)                  |
| `206`       | Partial success (e.g., modification transaction fetch issue)                 |
| `400`       | Bad request (missing required fields, malformed data)                        |
| `403`       | Signature validation failed                                                  |
| `406`       | Cannot parse message header                                                  |
| `409-411`   | Storage errors                                                               |

## Event Processing Logic

### General Flow

1. **Signature Validation**: Validate HMAC signature against request body
2. **Header Parsing**: Extract message metadata (message_id, class_name, event_name, etc.)
3. **ID Extraction**: Determine merchant identifier or Vindicia ID based on event type
4. **Storage**: Store event to S3 in organized structure
5. **Follow-up Actions**: Execute event-specific business logic

### Special Event Handling

#### AutoBills - Modify Event (`autobills/modify`)

When an AutoBill is modified, a pro-rated transaction may occur. The system:

1. Fetches transactions for the AutoBill within 300 seconds of the event
2. Looks for a transaction with `vin:type=modify` metadata
3. If found, stores the transaction as a `transactions/modify` event
4. Returns appropriate status based on whether modification transaction was found

#### Transactions - Attempt Succeeded (`transactions/attempt succeeded`)

For successful transactions generated by AutoBills:

- **Initial Billing** (`autoBillCycle == 0`): Fetches updated AutoBill (status changed to Active)
- **Successful Retry** (`retryNumber > 0`): Fetches updated AutoBill (billingState changed to Good Standing)

#### Transactions - Attempt Failed (`transactions/attempt failed`)

For failed transactions generated by AutoBills:

- **First Decline** (`autoBillCycle > 0` and `retryNumber == 0`): Fetches AutoBill (billingState → In Retry or Unusable Payment Method)
- **Last Retry** (`retryNumber >= RETRY_COUNT`): Fetches AutoBill for final state

### Supported Event Types

| Class Name        | Event Names                                                | Special Handling |
|:------------------|:-----------------------------------------------------------|:-----------------|
| `accounts`        | `data change`                                              | None             |
| `adjustments`     | `refund`                                                   | None             |
| `autobills`       | `start`, `stop`, `modify`                                  | Yes (modify)     |
| `transactions`    | `attempt succeeded`, `attempt failed`                      | Yes (both)       |
| `entitlement`     | `start`, `stop`                                            | None             |
| `invoices`        | `payment received`, `pre-notification`, `status change`    | None             |
| `payment methods` | Various                                                    | None             |

## Local Development & Testing

### Local Invocation

The handler supports local testing with automatic HMAC signature computation:

```bash
serverless invoke local --function receiver -p test/json/autobills_start.json
```

When running locally, if the event doesn't contain HTTP headers, the handler automatically:
1. Computes the HMAC signature
2. Wraps the payload in a simulated API Gateway event structure

### Test Files

Sample webhook payloads are in the `test/` directory:

```
test/
├── json/
│   ├── autobills_start.json
│   ├── autobills_modify.json
│   ├── transactions-attempt_succeeded.json
│   ├── transactions_attempt-failed.json
│   └── ...
```

### Debug Levels

Set `debug` environment variable in `serverless.yml`:

- **0**: INFO level (default)
- **1-2**: DEBUG level with basic details
- **3**: DEBUG with received signature and body
- **4**: DEBUG with Subscribe API responses
- **5**: DEBUG with full API request/response details

### Running Without Deployment

For rapid development without deploying to AWS:

```bash
serverless invoke local --function receiver -p test/json/transactions-attempt_succeeded.json
```

Note: S3 storage won't work locally unless using `serverless-s3-local` plugin.

## Project Structure

```
webhook-receiver/
├── handler.py                 # Lambda entry point
├── eventManager.py            # Core event processing logic
├── config.py                  # Configuration and logging setup
├── utils.py                   # Utility functions (validation, storage, API calls)
├── requirements.txt           # Python dependencies
├── serverless.yml             # Serverless Framework configuration
├── serverless-private.yml     # Private/local overrides (gitignored)
├── package.json               # Node.js dependencies (Serverless plugins)
├── README.md                  # This file
├── test/                      # Test webhook payloads
│   ├── json/                  # JSON test files
│   └── ...
└── tmp/                       # Temporary files (gitignored)
```

### Key Functions

#### handler.py

- **`vin_event(event, context)`**: Main Lambda handler, validates/creates HMAC signature

#### eventManager.py

- **`event_manager(event)`**: Core router for webhook events, orchestrates validation, storage, and follow-up actions

#### utils.py

- **`validate(message_id, body, sig)`**: HMAC signature validation
- **`storeMessage(class_id, message)`**: Store event to S3
- **`get_modification_tx(message_id, autobill, event_timestamp)`**: Fetch modification transactions
- **`get_subscription(id)`**: Fetch AutoBill by VID when billing state changes
- **`api_return(returnCode, **body)`**: Format API Gateway responses
- **`ct_compare(a, b)`**: Constant-time string comparison

## Troubleshooting

### Common Issues

#### Signature Validation Failure (403)

**Symptoms**: Webhooks return 403 Forbidden

**Solutions**:
- Verify `hmac_key` matches the key configured in Vindicia
- Ensure webhook body is not modified by API Gateway or other middleware
- Check that Content-Type is `application/json`

#### S3 Storage Errors (409-411)

**Symptoms**: Events validated but not stored

**Solutions**:
- Verify S3 bucket exists and name matches `s3bucket` environment variable
- Check IAM role has `s3:*` permissions for the bucket
- Confirm bucket is in the same region as Lambda function

#### Missing merchantAutoBillId (400)

**Symptoms**: AutoBills/modify events fail with "Cannot set class ID"

**Solutions**:
- This is expected for some AutoBill modifications that don't include the merchant ID
- The code falls back to using VID (Vindicia ID)
- Check warning logs for details

#### Local Testing Not Working

**Symptoms**: Local invocation fails or doesn't match AWS behavior

**Solutions**:
- Ensure Python 3.9 is being used
- Install all requirements: `pip install -r requirements.txt`
- Use valid test JSON files from `test/json/` directory
- Set `TEST` as signature value for bypassing validation locally

### Logging

All logs include:
- Timestamp
- Log level
- Module and line number
- Message with message_id, class_name, and event_name context

View CloudWatch Logs:

```bash
serverless logs -f receiver --tail
```

Or via AWS Console:
1. Navigate to CloudWatch > Log Groups
2. Find `/aws/lambda/vin-webhook-dev-receiver`
3. View log streams

### Support & Contact

For issues related to:
- **Vindicia API**: Contact Vindicia Support
- **AWS Resources**: Check AWS documentation or support
- **Code Issues**: Check repository issues or contact development team