# Deployment & Operations Guide

Complete guide for deploying, monitoring, and maintaining the Vindicia Webhook Receiver service.

## Table of Contents

- [Initial Setup](#initial-setup)
- [Deployment Process](#deployment-process)
- [Configuration Management](#configuration-management)
- [Monitoring & Alerts](#monitoring--alerts)
- [Troubleshooting](#troubleshooting)
- [Maintenance](#maintenance)
- [Security Best Practices](#security-best-practices)
- [Disaster Recovery](#disaster-recovery)

## Initial Setup

### Prerequisites Checklist

- [ ] AWS Account with appropriate permissions
- [ ] AWS CLI installed and configured
- [ ] Node.js and npm installed
- [ ] Python 3.9 installed
- [ ] Serverless Framework installed globally
- [ ] Git repository cloned
- [ ] Vindicia account credentials available
- [ ] HMAC key from Vindicia

### AWS Permissions Required

Create an IAM user or role with the following policies:

**Minimum Required Permissions**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:*",
        "s3:*",
        "logs:*",
        "iam:*",
        "apigateway:*",
        "lambda:*",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
        "events:*"
      ],
      "Resource": "*"
    }
  ]
}
```

**S3 Bucket Policy** (for message storage):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::ACCOUNT-ID:role/vin-webhook-STAGE-REGION-lambdaRole"
      },
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl"
      ],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

### Step-by-Step Initial Setup

#### 1. Create S3 Bucket

```bash
# Create bucket for webhook storage
aws s3 mb s3://your-webhook-bucket-name --region us-east-1

# Enable versioning (optional but recommended)
aws s3api put-bucket-versioning \
  --bucket your-webhook-bucket-name \
  --versioning-configuration Status=Enabled

# Configure lifecycle policy (optional - archive old events)
aws s3api put-bucket-lifecycle-configuration \
  --bucket your-webhook-bucket-name \
  --lifecycle-configuration file://lifecycle-policy.json
```

**Example lifecycle-policy.json**:
```json
{
  "Rules": [
    {
      "Id": "Archive old webhooks",
      "Status": "Enabled",
      "Prefix": "",
      "Transitions": [
        {
          "Days": 90,
          "StorageClass": "GLACIER"
        }
      ]
    }
  ]
}
```

#### 2. Configure AWS CLI

```bash
aws configure
# AWS Access Key ID: YOUR_ACCESS_KEY
# AWS Secret Access Key: YOUR_SECRET_KEY
# Default region name: us-east-1
# Default output format: json

# Verify configuration
aws sts get-caller-identity
```

#### 3. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Serverless plugins
npm install
```

#### 4. Configure serverless.yml

Create `serverless-private.yml` for sensitive configuration:

```yaml
# serverless-private.yml (DO NOT commit to git)
provider:
  environment:
    hmac_key: 'your-40-character-hmac-key-from-vindicia'
    api_key: 'api_username:api_password'
    s3bucket: 'your-webhook-bucket-name'
```

Then include it in `serverless.yml`:

```yaml
# At the top of serverless.yml
custom:
  privateConfig: ${file(./serverless-private.yml)}

# In provider.environment section
provider:
  environment:
    hmac_key: ${self:custom.privateConfig.provider.environment.hmac_key}
    api_key: ${self:custom.privateConfig.provider.environment.api_key}
    s3bucket: ${self:custom.privateConfig.provider.environment.s3bucket}
    # ... other variables
```

#### 5. Update IAM Role in serverless.yml

```yaml
provider:
  iam:
    role:
      statements:
      - Effect: "Allow"
        Action:
        - "s3:PutObject"
        - "s3:PutObjectAcl"
        Resource: "arn:aws:s3:::YOUR-BUCKET-NAME/*"
```

## Deployment Process

### Development Environment

```bash
# Deploy to dev stage
serverless deploy --stage dev

# Expected output:
# Serverless: Packaging service...
# Serverless: Excluding development dependencies...
# Serverless: Creating Stack...
# Serverless: Checking Stack create progress...
# ...
# endpoints:
#   POST - https://abc123xyz.execute-api.us-east-1.amazonaws.com/dev/event_manager
# functions:
#   receiver: vin-webhook-dev-receiver
```

**Note the endpoint URL** - you'll need this for Vindicia webhook configuration.

### Staging Environment

```bash
# Deploy to staging with specific region
serverless deploy --stage staging --region us-west-2
```

### Production Environment

```bash
# Deploy to production
serverless deploy --stage prod

# With additional safety:
serverless deploy --stage prod --verbose

# Deploy only function code (faster for hot fixes)
serverless deploy function -f receiver --stage prod
```

### Verification After Deployment

1. **Check Lambda function**:
   ```bash
   aws lambda get-function --function-name vin-webhook-prod-receiver
   ```

2. **Check API Gateway endpoint**:
   ```bash
   aws apigateway get-rest-apis
   ```

3. **Test with sample webhook**:
   ```bash
   curl -X POST https://YOUR-ENDPOINT/event_manager \
     -H "Content-Type: application/json" \
     -H "X-Webhook-Signature: TEST" \
     -d @test/json/autobills_start.json
   ```

4. **Check CloudWatch Logs**:
   ```bash
   serverless logs -f receiver --stage prod --tail
   ```

### Rollback Process

If deployment fails or causes issues:

```bash
# Rollback to previous deployment
serverless rollback --timestamp TIMESTAMP

# To view available deployments
serverless deploy list
```

## Configuration Management

### Environment-Specific Configuration

Create separate config files for each environment:

```yaml
# serverless-dev.yml
provider:
  environment:
    debug: 3
    api_env: Staging
    api_base: 'https://api.staging.vindicia.com'

# serverless-prod.yml
provider:
  environment:
    debug: 1
    api_env: Production
    api_base: 'https://api.vindicia.com'
```

Load based on stage:

```yaml
# serverless.yml
custom:
  stageConfig: ${file(./serverless-${self:provider.stage}.yml)}

provider:
  environment: ${self:custom.stageConfig.provider.environment}
```

### Secrets Management (Advanced)

**Option 1: AWS Systems Manager Parameter Store**

```bash
# Store secrets
aws ssm put-parameter \
  --name "/webhook-receiver/prod/hmac-key" \
  --value "your-hmac-key" \
  --type "SecureString"

# Reference in serverless.yml
provider:
  environment:
    hmac_key: ${ssm:/webhook-receiver/${self:provider.stage}/hmac-key}
```

**Option 2: AWS Secrets Manager**

```bash
# Store secrets
aws secretsmanager create-secret \
  --name webhook-receiver/prod/credentials \
  --secret-string '{"hmac_key":"...","api_key":"..."}'

# Lambda needs IAM permission to read secret
provider:
  iam:
    role:
      statements:
      - Effect: "Allow"
        Action: "secretsmanager:GetSecretValue"
        Resource: "arn:aws:secretsmanager:REGION:ACCOUNT:secret:webhook-receiver/*"
```

Then load in `config.py`:

```python
import boto3
import json

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])

if 'AWS_LAMBDA_FUNCTION_NAME' in os.environ:
    secrets = get_secret(f"webhook-receiver/{os.environ.get('STAGE', 'dev')}/credentials")
    HMAC_KEY = secrets['hmac_key']
    API_CREDS = secrets['api_key'].split(':')
else:
    HMAC_KEY = os.environ["hmac_key"]
    API_CREDS = os.environ["api_key"].split(":")
```

### Configuration Validation

Add validation function in `config.py`:

```python
def validate_config():
    errors = []
    
    if len(HMAC_KEY) != 40:
        errors.append("HMAC_KEY must be 40 characters")
    
    if DEBUG not in range(0, 6):
        errors.append("DEBUG must be between 0 and 5")
    
    if API_ENV not in ['Production', 'Staging']:
        errors.append("API_ENV must be 'Production' or 'Staging'")
    
    if errors:
        logger.error("Configuration errors: %s", errors)
        raise ValueError("Invalid configuration")

# Run on import
validate_config()
```

## Monitoring & Alerts

### CloudWatch Metrics

**Default Lambda Metrics**:
- Invocations: Number of webhook receptions
- Errors: Count of failed executions
- Duration: Execution time
- Throttles: Rate limiting events
- Concurrent Executions: Active Lambda instances

**View Metrics**:

```bash
# Via CLI
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=vin-webhook-prod-receiver \
  --start-time 2024-01-15T00:00:00Z \
  --end-time 2024-01-15T23:59:59Z \
  --period 3600 \
  --statistics Sum

# Via Console
# CloudWatch → Metrics → Lambda → By Function Name
```

### Custom Metrics (Enhanced Monitoring)

Add custom metrics to track business events:

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

def publish_metric(metric_name, value, unit='Count'):
    cloudwatch.put_metric_data(
        Namespace='WebhookReceiver',
        MetricData=[{
            'MetricName': metric_name,
            'Value': value,
            'Unit': unit,
            'Timestamp': datetime.utcnow()
        }]
    )

# In eventManager.py
def event_manager(event):
    # ... processing ...
    
    publish_metric(f"Webhook_{class_name}_{event_name}", 1)
    
    if response_code == "200":
        publish_metric("WebhookSuccess", 1)
    else:
        publish_metric("WebhookFailure", 1)
```

### CloudWatch Alarms

Create alarms for critical issues:

```bash
# High error rate alarm
aws cloudwatch put-metric-alarm \
  --alarm-name webhook-receiver-high-errors \
  --alarm-description "Webhook error rate > 5% over 5 minutes" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=vin-webhook-prod-receiver \
  --evaluation-periods 1 \
  --alarm-actions arn:aws:sns:us-east-1:ACCOUNT:ops-alerts

# Long duration alarm
aws cloudwatch put-metric-alarm \
  --alarm-name webhook-receiver-slow-execution \
  --metric-name Duration \
  --namespace AWS/Lambda \
  --statistic Average \
  --period 300 \
  --threshold 5000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=vin-webhook-prod-receiver \
  --evaluation-periods 2
```

### CloudWatch Logs Insights Queries

**Query for errors**:

```sql
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 100
```

**Query for signature failures**:

```sql
fields @timestamp, message_id, class_name, event_name
| filter @message like /Signatures do not match/
| stats count() by bin(5m)
```

**Query for specific event types**:

```sql
fields @timestamp, message_id, class_name, event_name
| filter class_name = "transactions" and event_name = "attempt failed"
| stats count() by bin(1h)
```

**Query for performance analysis**:

```sql
fields @timestamp, @duration, message_id
| stats avg(@duration), max(@duration), min(@duration), count()
| sort @duration desc
```

### SNS Alerts

Create SNS topic for operational alerts:

```bash
# Create SNS topic
aws sns create-topic --name webhook-receiver-alerts

# Subscribe email
aws sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:ACCOUNT:webhook-receiver-alerts \
  --protocol email \
  --notification-endpoint ops-team@example.com

# Subscribe to Slack (requires Lambda integration)
# Subscribe to PagerDuty (requires HTTPS endpoint)
```

### Logging Best Practices

**Structured Logging**:

```python
import json
import logging

logger = logging.getLogger('root')

def log_event(level, event_type, message, **kwargs):
    log_entry = {
        'level': level,
        'event_type': event_type,
        'message': message,
        **kwargs
    }
    
    if level == 'ERROR':
        logger.error(json.dumps(log_entry))
    elif level == 'WARNING':
        logger.warning(json.dumps(log_entry))
    else:
        logger.info(json.dumps(log_entry))

# Usage
log_event('INFO', 'webhook_received', 'Processing webhook',
          message_id=message_id, class_name=class_name)
```

**Log Aggregation**:
- Use CloudWatch Logs Insights for ad-hoc queries
- Export to S3 for long-term storage and analysis
- Consider Elasticsearch or Splunk for advanced analytics

## Troubleshooting

### Common Issues & Solutions

#### Issue: Webhook returns 403 (Signature Validation Failed)

**Symptoms**: All webhooks rejected with "Signature does not match"

**Diagnosis**:

```bash
# Check if HMAC key is correct
aws lambda get-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --query 'Environment.Variables.hmac_key'

# Enable debug logging temporarily
aws lambda update-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --environment "Variables={...,debug=3}"

# Check logs for signature details
serverless logs -f receiver --stage prod --tail
```

**Solutions**:
1. Verify HMAC key matches Vindicia configuration
2. Ensure Lambda environment variable is set correctly
3. Check for middleware modifying request body
4. Verify Content-Type is `application/json`

#### Issue: S3 Storage Failures (411)

**Symptoms**: Logs show "Error storing message"

**Diagnosis**:

```bash
# Check S3 bucket exists
aws s3 ls s3://your-bucket-name

# Check Lambda IAM permissions
aws lambda get-policy --function-name vin-webhook-prod-receiver

# Test S3 write from Lambda
serverless invoke -f receiver --stage prod -d '{"test":"data"}'
```

**Solutions**:
1. Verify bucket name in environment variables
2. Check IAM role has S3 write permissions
3. Ensure bucket is in same region as Lambda (or cross-region allowed)
4. Check bucket policy allows Lambda execution role

#### Issue: Lambda Timeout

**Symptoms**: Webhooks timeout before completing

**Diagnosis**:

```bash
# Check timeout setting
aws lambda get-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --query 'Timeout'

# Check duration metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=vin-webhook-prod-receiver \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Maximum,Average
```

**Solutions**:
1. Increase Lambda timeout (default 6s, max 15 minutes):
   ```yaml
   # serverless.yml
   functions:
     receiver:
       timeout: 30  # seconds
   ```
2. Optimize API calls to Vindicia
3. Consider async processing for follow-up actions

#### Issue: Memory Issues

**Symptoms**: Lambda out of memory errors

**Diagnosis**:

```bash
# Check memory configuration
aws lambda get-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --query 'MemorySize'

# Check logs for memory usage
serverless logs -f receiver --stage prod | grep "Memory"
```

**Solutions**:
1. Increase memory allocation:
   ```yaml
   # serverless.yml
   functions:
     receiver:
       memorySize: 512  # MB (default: 1024)
   ```
2. Optimize code to reduce memory usage
3. Process large payloads in chunks

### Debugging Techniques

#### Enable Debug Mode Temporarily

```bash
# Increase debug level
aws lambda update-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --environment "{\"Variables\":{\"debug\":\"5\", ...other vars...}}"

# Test webhook
curl -X POST ... | jq

# Restore normal logging
aws lambda update-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --environment "{\"Variables\":{\"debug\":\"1\", ...}}"
```

#### Local Debugging

```python
# Add breakpoints in code
import pdb; pdb.set_trace()

# Run locally
serverless invoke local -f receiver -p test/json/test-event.json
```

#### Remote Debugging with AWS SAM

```bash
# Install AWS SAM CLI
pip install aws-sam-cli

# Debug Lambda locally
sam local invoke receiver -e test-event.json --debug-port 5858
```

### Performance Optimization

**Cold Start Optimization**:

```yaml
# serverless.yml - Reduce package size
package:
  individually: true
  patterns:
    - '!test/**'
    - '!node_modules/**'
    - '!*.md'

# Use Python 3.9+ for faster cold starts
provider:
  runtime: python3.9
```

**Provisioned Concurrency** (for high-volume production):

```yaml
functions:
  receiver:
    provisionedConcurrency: 5  # Keep 5 instances warm
```

## Maintenance

### Routine Maintenance Tasks

#### Daily

- [ ] Check CloudWatch alarm status
- [ ] Review error logs for anomalies
- [ ] Verify webhook delivery rate matches expected volume

#### Weekly

- [ ] Review CloudWatch Insights for trends
- [ ] Check S3 bucket size and growth rate
- [ ] Audit failed webhooks and retry patterns

#### Monthly

- [ ] Review and update dependencies
- [ ] Analyze Lambda performance metrics
- [ ] Review and rotate API keys (if needed)
- [ ] Test disaster recovery procedures

#### Quarterly

- [ ] Security audit (IAM permissions, secret rotation)
- [ ] Cost optimization review
- [ ] Update documentation
- [ ] Test backup and restore procedures

### Dependency Updates

```bash
# Check for outdated Python packages
pip list --outdated

# Update requirements.txt
pip install --upgrade boto3 requests
pip freeze > requirements.txt

# Check for outdated npm packages
npm outdated

# Update package.json
npm update

# Deploy updates
serverless deploy --stage dev  # Test first
serverless deploy --stage prod  # Production
```

### Security Patching

```bash
# Check for security vulnerabilities
pip-audit  # Install with: pip install pip-audit
npm audit

# Update vulnerable packages
pip install --upgrade PACKAGE_NAME
npm audit fix

# Redeploy
serverless deploy --stage prod
```

## Security Best Practices

### Secrets Management Checklist

- [ ] Never commit secrets to git
- [ ] Use environment variables or AWS Secrets Manager
- [ ] Rotate HMAC keys regularly (every 90 days)
- [ ] Rotate API credentials regularly
- [ ] Use least-privilege IAM policies
- [ ] Enable S3 bucket encryption
- [ ] Enable CloudWatch Logs encryption

### IAM Best Practices

**Lambda Execution Role (Least Privilege)**:

```yaml
provider:
  iam:
    role:
      statements:
      - Effect: "Allow"
        Action:
          - "s3:PutObject"  # Only write, not read or delete
        Resource: "arn:aws:s3:::webhook-bucket/*"
      - Effect: "Allow"
        Action:
          - "logs:CreateLogGroup"
          - "logs:CreateLogStream"
          - "logs:PutLogEvents"
        Resource: "arn:aws:logs:*:*:log-group:/aws/lambda/vin-webhook-*"
```

### Audit Logging

Enable CloudTrail for API auditing:

```bash
aws cloudtrail create-trail \
  --name webhook-receiver-audit \
  --s3-bucket-name audit-logs-bucket

aws cloudtrail start-logging --name webhook-receiver-audit
```

### Network Security

**VPC Configuration** (optional, for private resources):

```yaml
# serverless.yml
provider:
  vpc:
    securityGroupIds:
      - sg-xxxxxx
    subnetIds:
      - subnet-xxxxxx
      - subnet-yyyyyy
```

**Note**: Using VPC adds cold start latency. Only needed if accessing private resources.

## Disaster Recovery

### Backup Strategy

#### Lambda Function Backup

```bash
# Download function code
aws lambda get-function \
  --function-name vin-webhook-prod-receiver \
  --query 'Code.Location' \
  | xargs curl -o lambda-backup.zip

# Export function configuration
aws lambda get-function-configuration \
  --function-name vin-webhook-prod-receiver \
  > lambda-config-backup.json
```

#### S3 Data Backup

```bash
# Enable versioning (prevents accidental deletion)
aws s3api put-bucket-versioning \
  --bucket your-webhook-bucket \
  --versioning-configuration Status=Enabled

# Cross-region replication for DR
aws s3api put-bucket-replication \
  --bucket your-webhook-bucket \
  --replication-configuration file://replication-config.json
```

**replication-config.json**:
```json
{
  "Role": "arn:aws:iam::ACCOUNT:role/s3-replication-role",
  "Rules": [{
    "Status": "Enabled",
    "Priority": 1,
    "Filter": {},
    "Destination": {
      "Bucket": "arn:aws:s3:::backup-webhook-bucket"
    }
  }]
}
```

### Recovery Procedures

#### Recover from Accidental Deletion

```bash
# Redeploy from code repository
git checkout main
serverless deploy --stage prod

# Restore S3 objects (if versioning enabled)
aws s3api list-object-versions \
  --bucket your-webhook-bucket \
  --prefix 20240115/

aws s3api restore-object \
  --bucket your-webhook-bucket \
  --key 20240115/transactions/attempt succeeded/message-id
```

#### Recover from Region Failure

```bash
# If using cross-region replication, promote backup bucket
# Update Lambda to use backup bucket

# Deploy to alternate region
serverless deploy --stage prod --region us-west-2

# Update Vindicia webhook URL to new endpoint
```

### Testing DR Procedures

**Quarterly DR Test**:

1. Deploy to test region
2. Configure test webhook in Vindicia staging
3. Send test webhooks
4. Verify storage and processing
5. Test failover time
6. Document findings

```bash
# DR test script
#!/bin/bash
echo "Starting DR test..."

# Deploy to DR region
serverless deploy --stage dr-test --region us-west-2

# Get endpoint
ENDPOINT=$(serverless info --stage dr-test --region us-west-2 | grep POST | awk '{print $3}')

# Test webhook
curl -X POST $ENDPOINT/event_manager \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: TEST" \
  -d @test/json/test-webhook.json

# Verify logs
serverless logs -f receiver --stage dr-test --region us-west-2

echo "DR test complete"
```

### Recovery Time Objectives (RTO)

| Scenario | Target RTO | Procedure |
|:---------|:-----------|:----------|
| Lambda function failure | 5 minutes | Automatic retry by AWS |
| Code bug deployment | 15 minutes | Rollback deployment |
| Configuration error | 10 minutes | Update environment variables |
| S3 bucket issue | 30 minutes | Redirect to backup bucket |
| Region failure | 2 hours | Failover to alternate region |

### Recovery Point Objectives (RPO)

| Data Type | Target RPO | Strategy |
|:----------|:-----------|:---------|
| Webhook events | 0 seconds | S3 versioning + replication |
| Lambda configuration | 24 hours | Daily configuration backups |
| Application code | 0 seconds | Git version control |

---

## Additional Resources

### Useful Commands

```bash
# View all deployments
serverless deploy list

# View function info
serverless info --stage prod

# Tail logs
serverless logs -f receiver --tail --stage prod

# Invoke function remotely
serverless invoke -f receiver --stage prod --data '...'

# Remove deployment
serverless remove --stage dev

# Package without deploying
serverless package

# Print compiled CloudFormation template
serverless print

# Validate serverless.yml
serverless print --format yaml
```

### Monitoring Dashboard

Create CloudWatch Dashboard:

```bash
aws cloudwatch put-dashboard \
  --dashboard-name WebhookReceiverProd \
  --dashboard-body file://dashboard-config.json
```

**dashboard-config.json** (example):
```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          [ "AWS/Lambda", "Invocations", { "stat": "Sum" } ],
          [ ".", "Errors", { "stat": "Sum" } ],
          [ ".", "Throttles", { "stat": "Sum" } ]
        ],
        "period": 300,
        "stat": "Average",
        "region": "us-east-1",
        "title": "Lambda Metrics"
      }
    }
  ]
}
```

### Cost Optimization

**Estimated Costs** (us-east-1, as of 2024):

| Component | Usage | Cost/Month |
|:----------|:------|:-----------|
| Lambda | 1M invocations, 200ms avg | $0.20 |
| API Gateway | 1M requests | $3.50 |
| S3 Storage | 10GB | $0.23 |
| S3 Requests | 1M PUT | $5.00 |
| CloudWatch Logs | 5GB | $2.50 |
| **Total** | | **~$12/month** |

**Optimization Tips**:
- Use S3 Lifecycle policies to archive old data to Glacier
- Reduce Lambda memory if not needed (billed by GB-second)
- Use CloudWatch Logs retention policies
- Consider S3 Intelligent-Tiering for storage

### Support Contacts

- **AWS Support**: Via AWS Console or CLI
- **Serverless Framework**: https://serverless.com/support
- **Vindicia Support**: support@vindicia.com
- **Internal Ops Team**: ops-team@example.com

---

**Last Updated**: 2024
**Document Version**: 1.0
