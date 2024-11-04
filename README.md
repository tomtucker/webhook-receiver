# Webhook Receiver

A robust webhook receiver service that handles incoming webhook notifications with HMAC signature validation.

This version uses the Serverless Framework to deploy to AWS Lambda and handle webhook payloads asynchronously via SNS.

## Features

- HMAC signature validation for secure webhook processing
- Configurable logging levels
- JSON payload processing
- AWS Lambda compatible
  - S3 bucket integration
- Serverless Framework
  - Applications defined through simple abstract syntax in YAML.
  - AWS Lambda functions, triggers & code deployed and wired together in the cloud, automatically.
  - Local execution and testing of Lambda function.
  - Serverless Plugins
    -  Local execution (except for S3 storage) for testing Lambda function logic
    - Packaging optimization to reduce deployment package size
    - Automatically bundle dependencies from `requirements.txt` and make them available in PYTHONPATH
    - Automated deployment to AWS
- Flexible event message behaviors

## Pre-requisites

* AWS Account
  * AWS IAM user with necessary permissions
  * AWS S3 Bucket for storing recieved messages
* AWS CLI installed & configured locally
* Serverless Framework installed locally
  * https://www.serverless.com/framework/docs/getting-started
* Python 3.9 for local execution
  * Python modules in `requirements.txt`

## Environment Variables

Configuration settings are set in the Lambda environment through the serverless.yml template:

| Key        | Description                                                                                                                            | Example/Default       |
| :--------- | :------------------------------------------------------------------------------------------------------------------------------------- | :-------------------- |
| api_env    | Environment to access for retrieving objects. If set to any value other then 'Production', Subscribe Staging environemnt will be used | Staging               |
| api_key    | Subscribe API username and password separated by a colon (:)                                                                           | api_user:api_password |
| api_version | CashBox SOAP API version to use when retrieving objects. MUST BE A STRING SO QUOTE IT                                                  | '27.0'                |
| hmac_key   | 40 Character authentication key provided for verification of the integrity of Subscribe push notifications                             | None                  |
| region     | AWS Region                                                                                                                             | us-east-1             |
| s3bucket   | Name of S3 Bucket to use for storing messages. Be sure to update 'iamRoleStatements' to allow access to this S3 Bucket                 | vin.eventmanager      |
| debug      | Debug output level. Higher values (up to 5) increase the logging output (written to CloudWatch by AWS Lambda by default)               | 0                     |

The following environment variables are required:

- `hmac_key`: Secret key for HMAC validation
- `s3bucket`: S3 bucket name for storage

## API Endpoints
The successful serverless post deploy summary will provide the information we need about our end point.

### Webhook Handler

Endpoint will be accept POST requests with the following requirements:

#### Headers
- `X-Webhook-Signature`: HMAC signature for request validation

#### Request Body
JSON payload with required structure according to the Subscribe documenation.