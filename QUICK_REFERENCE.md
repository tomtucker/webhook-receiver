# Quick Reference Guide

Fast reference for common tasks and commands.

## Essential Commands

### Deployment

```bash
# Deploy to dev
serverless deploy --stage dev

# Deploy to production
serverless deploy --stage prod

# Deploy function only (faster)
serverless deploy function -f receiver --stage prod

# Remove deployment
serverless remove --stage dev
```

### Testing

```bash
# Local test
serverless invoke local -f receiver -p test/json/autobills_start.json

# Remote test
serverless invoke -f receiver --stage prod -d '{"test":"data"}'

# Check logs
serverless logs -f receiver --stage prod --tail
```

### Monitoring

```bash
# Tail logs
serverless logs -f receiver --tail

# View metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=vin-webhook-prod-receiver \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

## HTTP Status Codes

| Code | Meaning | Action |
|:-----|:--------|:-------|
| 200 | Success | Event fully processed |
| 202 | Accepted | Event stored, follow-up issue |
| 206 | Partial | Event stored, modification tx issue |
| 400 | Bad Request | Malformed event, check structure |
| 403 | Forbidden | Signature mismatch, check HMAC key |
| 406 | Not Acceptable | Cannot parse header |
| 409 | Conflict | S3 resource error |
| 410 | Gone | Cannot extract message fields |
| 411 | Length Required | S3 storage failure |

## Environment Variables

| Variable | Required | Example |
|:---------|:---------|:--------|
| hmac_key | Yes | 40-character key |
| s3bucket | Yes | vin.eventmanager |
| region | Yes | us-east-1 |
| debug | Yes | 0-5 |
| api_env | Yes | Staging/Production |
| api_key | Yes | username:password |
| api_base | Yes | https://api.staging.vindicia.com |
| api_version | Yes | '27.0' |

## Event Processing Matrix

| Class | Event | ID Location | Special Handling |
|:------|:------|:------------|:-----------------|
| accounts | data change | content.account.merchantAccountId | None |
| adjustments | refund | content.merchantRefundId | None |
| autobills | start, stop | content.merchantAutoBillId | None |
| autobills | modify | content.autobill.merchantAutoBillId | Fetch modification tx |
| transactions | attempt succeeded | content.merchantTransactionId | Fetch AutoBill if cycle=0 or retry>0 |
| transactions | attempt failed | content.merchantTransactionId | Fetch AutoBill if first/last retry |
| entitlement | start, stop | content.merchantAccountId | None |
| invoices | * | header.invoice_id | None |
| payment methods | * | content.merchantPaymentMethodId | None |

## S3 Storage Structure

```
bucket-name/
  YYYYMMDD/                    (date partition)
    class_name/                (e.g., transactions)
      event_name/              (e.g., attempt succeeded)
        message_id             (unique event file)
```

## Debug Levels

| Level | Output |
|:------|:-------|
| 0 | INFO only (production) |
| 1-2 | DEBUG basic |
| 3 | DEBUG with signatures & body |
| 4 | DEBUG with API responses |
| 5 | DEBUG with full API details |

## Common Issues

### Signature Validation Failure

```bash
# Check HMAC key
aws lambda get-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --query 'Environment.Variables.hmac_key'

# Enable debug logging
aws lambda update-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --environment "Variables={debug=3,...}"
```

### S3 Storage Failure

```bash
# Verify bucket
aws s3 ls s3://your-bucket-name

# Check IAM permissions
aws lambda get-policy --function-name vin-webhook-prod-receiver

# Test write
aws s3 cp test.txt s3://your-bucket-name/test.txt
```

### Lambda Timeout

```yaml
# Increase timeout in serverless.yml
functions:
  receiver:
    timeout: 30  # seconds (max 900)
```

## Useful AWS CLI Commands

```bash
# Function info
aws lambda get-function --function-name vin-webhook-prod-receiver

# Update environment variable
aws lambda update-function-configuration \
  --function-name vin-webhook-prod-receiver \
  --environment "Variables={debug=1,hmac_key=...,s3bucket=...}"

# Invoke function
aws lambda invoke \
  --function-name vin-webhook-prod-receiver \
  --payload '{"test":"data"}' \
  response.json

# View recent logs
aws logs tail /aws/lambda/vin-webhook-prod-receiver --follow
```

## CloudWatch Logs Insights Queries

### Find errors
```sql
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 100
```

### Signature failures
```sql
fields @timestamp, message_id
| filter @message like /Signatures do not match/
| stats count() by bin(5m)
```

### Event type distribution
```sql
fields class_name, event_name
| stats count() by class_name, event_name
```

### Performance analysis
```sql
fields @timestamp, @duration
| stats avg(@duration), max(@duration), percentile(@duration, 95)
```

## Test Files Location

```
test/
  json/
    autobills_start.json
    autobills_modify.json
    autobills_stop.json
    transactions-attempt_succeeded.json
    transactions_attempt-failed.json
    entitlement-start.json
    entitlement-stop.json
    invoices-payment_received.json
    ...
  DGD-18692/          (specific test cases)
  DGD-19787/          (specific test cases)
```

## Curl Test Example

```bash
# Test webhook endpoint
curl -X POST https://YOUR-ENDPOINT/event_manager \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: YOUR_SIGNATURE" \
  -d @test/json/autobills_start.json

# With local signature bypass
curl -X POST https://YOUR-ENDPOINT/event_manager \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: TEST" \
  -d @test/json/autobills_start.json
```

## Emergency Procedures

### Disable Webhook Processing

```bash
# Remove API Gateway endpoint
aws apigateway delete-rest-api --rest-api-id YOUR_API_ID

# Or update Lambda to return error
aws lambda update-function-code \
  --function-name vin-webhook-prod-receiver \
  --zip-file fileb://emergency-stub.zip
```

### Rollback Deployment

```bash
# List deployments
serverless deploy list

# Rollback to timestamp
serverless rollback --timestamp TIMESTAMP
```

### Emergency Contact

1. Check CloudWatch alarms
2. Review recent deployments
3. Check Vindicia status page
4. Escalate to ops team if needed

## Performance Benchmarks

| Metric | Target | Alert Threshold |
|:-------|:-------|:----------------|
| Duration (avg) | <200ms | >1000ms |
| Duration (p95) | <500ms | >2000ms |
| Error rate | <0.1% | >1% |
| Throttles | 0 | >0 |
| Cold start | <500ms | >2000ms |

## Resource Limits

| Resource | Default | Maximum |
|:---------|:--------|:--------|
| Lambda timeout | 6s | 900s (15 min) |
| Lambda memory | 128MB | 10240MB (10GB) |
| Lambda concurrent executions | 1000 | Request increase |
| API Gateway timeout | 29s | 29s (hard limit) |
| S3 object size | - | 5TB |

## Cost Estimates (Monthly)

Based on 1 million webhooks/month:

| Component | Cost |
|:----------|:-----|
| Lambda invocations | $0.20 |
| Lambda compute (200ms avg) | $0.33 |
| API Gateway | $3.50 |
| S3 storage (10GB) | $0.23 |
| S3 PUT requests | $5.00 |
| CloudWatch Logs (5GB) | $2.50 |
| **Total** | **~$12/month** |

## Security Checklist

- [ ] HMAC key configured and secure
- [ ] API credentials stored securely (not in code)
- [ ] IAM roles follow least privilege
- [ ] S3 bucket not publicly accessible
- [ ] CloudWatch Logs enabled
- [ ] Alarms configured for errors
- [ ] Secrets rotation schedule in place
- [ ] Backup/DR procedures tested

## Support Resources

- **README.md**: Project overview and getting started
- **ARCHITECTURE.md**: System design and components
- **CODE_DOCUMENTATION.md**: Detailed code reference
- **DEPLOYMENT_GUIDE.md**: Complete deployment procedures
- **This Guide**: Quick reference

## Vindicia Webhook Configuration

1. Log into Vindicia CashBox
2. Navigate to: Configuration > Webhooks
3. Click "Add Webhook"
4. Set URL: `https://YOUR-ENDPOINT/event_manager`
5. Set HMAC key (must match Lambda config)
6. Select event types to receive
7. Test webhook delivery
8. Enable webhook

## Version Information

- Python Runtime: 3.9
- Serverless Framework: 3.x
- AWS Lambda: Current
- boto3: See requirements.txt
- Last Updated: 2024
