# Complete Infrastructure Deployment & Teardown Guide

This guide provides scripts for deploying and tearing down the complete AthenaHealth AWS integration infrastructure, which consists of two CloudFormation stacks:

1. **Foundation Stack** - Core infrastructure (VPC, KMS, S3, Security Groups, CloudTrail, Config)
2. **Integration Stack** - Application layer (RDS, Lambda, API Gateway, VPC Endpoints)

## Files Overview

### CloudFormation Templates:
- `AthenaAWS-Sandbox-CloudFormationTemplate.yaml` - Foundation stack template
- `athenahealth-rds-integration.yaml` - Integration stack template

### Deployment Scripts:
- `deploy-complete-infrastructure.sh` - Bash deployment script
- `deploy-complete-infrastructure.py` - Python deployment script

### Teardown Scripts:
- `teardown-complete-infrastructure.sh` - Bash teardown script
- `teardown-complete-infrastructure.py` - Python teardown script

## Prerequisites

### For Bash Scripts:
- AWS CLI installed and configured
- Bash shell (Linux/Mac/WSL)
- `jq` installed (for JSON parsing)
- AWS credentials with appropriate permissions

### For Python Scripts:
- Python 3.6 or higher
- boto3 library: `pip install boto3`
- AWS credentials configured

### Required AWS Permissions:
Your AWS credentials need permissions for:
- CloudFormation (full)
- EC2 (VPC, Subnets, Security Groups, NAT Gateway)
- RDS (full)
- Lambda (full)
- API Gateway (full)
- S3 (full)
- KMS (key management)
- Secrets Manager (full)
- IAM (role creation and management)
- CloudTrail
- Config
- CloudWatch Logs

## Deployment

### Quick Start - Bash:
```bash
# Make the script executable
chmod +x deploy-complete-infrastructure.sh

# Deploy without EC2 key pair (recommended for Lambda-only setup)
./deploy-complete-infrastructure.sh us-east-1

# Deploy with EC2 key pair (for bastion host access)
./deploy-complete-infrastructure.sh us-east-1 my-keypair-name
```

### Quick Start - Python:
```bash
# Deploy without EC2 key pair
python deploy-complete-infrastructure.py us-east-1

# Deploy with EC2 key pair
python deploy-complete-infrastructure.py us-east-1 my-keypair-name
```

### What the Deployment Script Does:

#### Step 1: Validates Template Files
- Checks that both CloudFormation templates exist in the current directory
- Validates syntax and structure with AWS

#### Step 2: Deploys Foundation Stack
Creates the core infrastructure:
- **VPC** with public and private subnets across 2 AZs
- **Internet Gateway** and **NAT Gateway**
- **KMS Key** for HIPAA-compliant encryption
- **S3 Buckets** for PHI data and logs (encrypted)
- **Security Groups** for bastion, application, and load balancer
- **CloudTrail** for audit logging
- **AWS Config** for compliance monitoring

Time: ~5-10 minutes

#### Step 3: Retrieves Foundation Outputs
Captures key information needed for the integration stack:
- VPC ID
- Private Subnet IDs
- KMS Key ID

#### Step 4: Deploys Integration Stack
Creates the application infrastructure:
- **RDS PostgreSQL** (Multi-AZ, encrypted, HIPAA-compliant)
- **Lambda Functions** (3):
  - Inbound: AthenaHealth API → RDS
  - Outbound: RDS → AthenaHealth API
  - Transform: Data processing
- **API Gateway** (private, VPC-based)
- **VPC Endpoints** for Secrets Manager and API Gateway
- **Secrets Manager** for DB and API credentials
- **Security Groups** for Lambda and RDS
- **CloudWatch Log Groups** (encrypted)

Time: ~10-15 minutes

#### Total Deployment Time: 15-25 minutes

### Deployment Output:
After successful deployment, you'll see:
```
=====================================
Deployment Complete!
=====================================

Infrastructure Summary:
  ✓ Foundation Stack: gov-health-foundation
  ✓ Integration Stack: gov-health-integration

Key Resources:
  - VPC ID: vpc-xxxxx
  - RDS Endpoint: gov-health-postgresql.xxxxx.us-east-1.rds.amazonaws.com
  - API Gateway: https://xxxxx.execute-api.us-east-1.amazonaws.com/prod

Next Steps:
1. Update AthenaHealth API credentials in Secrets Manager
2. Configure Lambda functions with your business logic
3. Initialize the RDS database schema
4. Test the integration endpoints
```

## Teardown

### Quick Start - Bash:
```bash
# Make the script executable
chmod +x teardown-complete-infrastructure.sh

# Run teardown
./teardown-complete-infrastructure.sh us-east-1
```

### Quick Start - Python:
```bash
python teardown-complete-infrastructure.py us-east-1
```

### What the Teardown Script Does:

#### Safety Confirmation:
You must type `DELETE` (all caps) to confirm deletion.

#### Step 1: Deletes Integration Stack
- Disables RDS deletion protection automatically
- Waits for RDS to be modifiable
- Deletes all Lambda functions
- Removes API Gateway
- Deletes VPC endpoints
- Removes security groups
- Creates final RDS snapshot (automatic)

Time: ~10-15 minutes

#### Step 2: Deletes Foundation Stack
- Prompts to empty S3 buckets (recommended)
  - PHI data bucket
  - Logs bucket
- Deletes VPC and all networking components
- Removes KMS keys (scheduled for deletion)
- Deletes CloudTrail and Config

Time: ~5-10 minutes

#### Step 3: Cleans Up Orphaned Resources
- Lists RDS snapshots
- Offers to delete snapshots (optional)
- Checks for leftover S3 buckets

#### Total Teardown Time: 15-25 minutes

### Teardown Output:
```
=====================================
Teardown Complete!
=====================================

Summary:
  ✓ Integration stack deleted
  ✓ Foundation stack deleted
  ✓ RDS database deleted (snapshot may exist)
  ✓ Lambda functions removed
  ✓ API Gateway deleted
  ✓ VPC and networking deleted

Potential remaining costs:
  - RDS snapshots (storage)
  - S3 buckets (if not emptied)
  - Secrets Manager (recovery period)
```

## Daily Sandbox Workflow

Perfect for cost-conscious development where you only pay for active hours.

### Morning - Start Work:
```bash
# Deploy the complete infrastructure
./deploy-complete-infrastructure.sh us-east-1

# Wait 15-25 minutes for deployment
# Begin development work
```

### Evening - Stop Work:
```bash
# Tear down the complete infrastructure
./teardown-complete-infrastructure.sh us-east-1

# When prompted:
# - Type 'DELETE' to confirm
# - Choose 'yes' to empty S3 buckets
# - Choose 'yes' to delete RDS snapshots (if no data to preserve)

# Wait 15-25 minutes for teardown
# No charges overnight!
```

## Cost Breakdown

### Active Infrastructure (deployed):
- **RDS PostgreSQL** (db.t3.medium Multi-AZ): ~$0.20/hour
- **NAT Gateway**: ~$0.045/hour + data transfer
- **Lambda**: $0.20 per 1M requests + compute
- **API Gateway**: $3.50 per 1M requests
- **VPC Endpoints**: $0.01/hour per AZ (~$0.02/hour total)
- **S3 Storage**: $0.023/GB/month
- **CloudWatch Logs**: $0.50/GB ingested

**Estimated hourly cost**: ~$0.30-0.40/hour ($2.40-3.20 for 8-hour workday)

### Overnight (torn down):
- **RDS Snapshots**: $0.095/GB/month (only if kept)
- **S3 Storage**: $0.023/GB/month (only if not emptied)
- **Secrets Manager**: $0.40/month per secret (during recovery period)

**Estimated overnight cost**: Near $0 if snapshots and S3 are cleaned

### Monthly Comparison:
- **24/7 Operation**: ~$220-290/month
- **8hrs/day, 20 days/month**: ~$48-64/month (78% savings)

## Architecture Overview

```
Foundation Stack:
┌─────────────────────────────────────────────────────────┐
│  VPC (10.0.0.0/16)                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Public       │  │ Private      │  │ Private      │ │
│  │ Subnet       │  │ Subnet 1     │  │ Subnet 2     │ │
│  │ (NAT/IGW)    │  │ (Apps)       │  │ (Apps)       │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │ KMS Key      │  │ S3 Buckets   │                    │
│  │ (Encryption) │  │ (PHI + Logs) │                    │
│  └──────────────┘  └──────────────┘                    │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │ CloudTrail   │  │ AWS Config   │                    │
│  │ (Audit)      │  │ (Compliance) │                    │
│  └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────┘

Integration Stack:
┌─────────────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────────┐  │
│  │ API Gateway (Private)                            │  │
│  │ /inbound  /outbound                              │  │
│  └──────────────────────────────────────────────────┘  │
│                        │                                 │
│  ┌─────────────────────┼────────────────────────────┐  │
│  │ Lambda Functions    │                            │  │
│  │ ┌─────────┐ ┌──────▼───┐ ┌──────────┐          │  │
│  │ │Inbound  │ │Transform │ │Outbound  │          │  │
│  │ └─────────┘ └──────────┘ └──────────┘          │  │
│  └───────────────────────────────────────────────────┘  │
│                        │                                 │
│  ┌─────────────────────▼────────────────────────────┐  │
│  │ RDS PostgreSQL (Multi-AZ, Encrypted)             │  │
│  │ ┌──────────────┐  ┌──────────────┐              │  │
│  │ │ Primary DB   │  │ Standby DB   │              │  │
│  │ └──────────────┘  └──────────────┘              │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │ Secrets Mgr  │  │ VPC Endpoints│                    │
│  │ (Credentials)│  │ (Private)    │                    │
│  └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────┘

Data Flow:
AthenaHealth API ← → Lambda (Inbound) → RDS
RDS → Lambda (Transform) → RDS
RDS → Lambda (Outbound) → AthenaHealth API
```

## Troubleshooting

### Deployment Issues:

**Stack creation fails:**
```bash
# Check CloudFormation events
aws cloudformation describe-stack-events \
  --stack-name gov-health-foundation \
  --region us-east-1 \
  --max-items 20

# Common issues:
# - Insufficient IAM permissions
# - VPC resource limits exceeded
# - Invalid key pair name
# - Region-specific constraints
```

**RDS creation timeout:**
- Multi-AZ RDS can take 15+ minutes
- Script will wait up to 20 minutes
- Check AWS Console for status

**Lambda deployment fails:**
- Check VPC/subnet configuration
- Verify security group rules
- Ensure KMS key permissions

### Teardown Issues:

**Stack deletion stuck:**
```bash
# Check what's blocking deletion
aws cloudformation describe-stack-resources \
  --stack-name gov-health-integration \
  --region us-east-1

# Common blockers:
# - RDS deletion protection still enabled (script handles this)
# - S3 buckets not empty
# - Active Lambda ENIs (wait 10-15 minutes)
```

**S3 bucket won't delete:**
```bash
# Manually empty versioned bucket
aws s3api list-object-versions \
  --bucket gov-health-phi-data-ACCOUNT_ID \
  --region us-east-1

# Use the teardown script's S3 emptying feature
# Or manually delete via AWS Console
```

**RDS snapshot issues:**
```bash
# List snapshots
aws rds describe-db-snapshots \
  --region us-east-1

# Delete specific snapshot
aws rds delete-db-snapshot \
  --db-snapshot-identifier snapshot-name \
  --region us-east-1
```

### Manual Cleanup:

If automated scripts fail:

```bash
# List all stacks
aws cloudformation list-stacks \
  --region us-east-1 \
  --query "StackSummaries[?contains(StackName,'gov-health')]"

# Force delete a stack (use with caution)
aws cloudformation delete-stack \
  --stack-name gov-health-integration \
  --region us-east-1

# Check for orphaned resources
aws ec2 describe-vpcs --region us-east-1
aws rds describe-db-instances --region us-east-1
aws lambda list-functions --region us-east-1
aws s3 ls | grep gov-health
```

## Post-Deployment Configuration

### 1. Update AthenaHealth API Credentials:
```bash
# Update the secret with your actual credentials
aws secretsmanager update-secret \
  --secret-id gov-health/athenahealth/api \
  --secret-string '{
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "api_base_url": "https://api.platform.athenahealth.com",
    "sandbox_url": "https://api.platform.athenahealth.com"
  }' \
  --region us-east-1
```

### 2. Initialize Database Schema:
Connect to RDS and run your schema initialization scripts.

### 3. Deploy Lambda Code:
Replace placeholder code with your actual business logic:
- Update the Lambda function code via AWS Console or CLI
- Add required dependencies as Lambda Layers
- Configure environment variables as needed

### 4. Test Integration:
```bash
# Get API Gateway endpoint
aws cloudformation describe-stacks \
  --stack-name gov-health-integration \
  --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='APIGatewayEndpoint'].OutputValue" \
  --output text

# Test inbound endpoint (adjust authentication as needed)
curl -X POST https://YOUR_API_GATEWAY_ID.execute-api.us-east-1.amazonaws.com/prod/inbound \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

## Security Best Practices

1. **Restrict SSH Access**: Update bastion security group to allow only your IP
2. **Enable MFA**: For all AWS accounts with admin access
3. **Rotate Credentials**: Regularly update Secrets Manager secrets
4. **Monitor Logs**: Review CloudTrail and application logs regularly
5. **Update IAM Policies**: Follow principle of least privilege
6. **Enable GuardDuty**: For threat detection (optional, additional cost)
7. **Configure VPC Flow Logs**: For network monitoring (optional)

## Support & Additional Resources

- AWS CloudFormation Documentation: https://docs.aws.amazon.com/cloudformation/
- AWS RDS Best Practices: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_BestPractices.html
- HIPAA on AWS: https://aws.amazon.com/compliance/hipaa-compliance/
- Lambda Best Practices: https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html

## License & Disclaimer

These scripts are provided as-is for educational and development purposes. Always review and test thoroughly before using in production environments. Ensure compliance with all applicable regulations (HIPAA, GDPR, etc.) for your specific use case.
