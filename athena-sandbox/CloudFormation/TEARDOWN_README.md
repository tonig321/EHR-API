# CloudFormation Stack Teardown Scripts

Two scripts are provided to safely delete your AthenaHealth integration stack:
- **teardown-stack.sh** - Bash script (Linux/Mac)
- **teardown-stack.py** - Python script (cross-platform)

## Prerequisites

### For Bash Script:
- AWS CLI installed and configured
- Bash shell (Linux/Mac/WSL)
- AWS credentials with appropriate permissions

### For Python Script:
- Python 3.6 or higher
- boto3 library: `pip install boto3`
- AWS credentials configured

## Usage

### Bash Script:
```bash
# Make the script executable
chmod +x teardown-stack.sh

# Run the script
./teardown-stack.sh <stack-name> <region>

# Example:
./teardown-stack.sh gov-health-athena-stack us-east-1
```

### Python Script:
```bash
python teardown-stack.py <stack-name> <region>

# Example:
python teardown-stack.py gov-health-athena-stack us-east-1
```

## What the Scripts Do

### Automated Steps:
1. **Verify Stack Exists** - Confirms the stack is present in the specified region
2. **Disable RDS Deletion Protection** - Removes deletion protection from the RDS instance
3. **Wait for RDS Ready** - Ensures RDS is in a modifiable state
4. **Delete CloudFormation Stack** - Initiates stack deletion
5. **Monitor Progress** - Tracks deletion status (takes 10-15 minutes)
6. **Check for Orphaned Resources** - Identifies leftover snapshots

### Manual Confirmations:
- Confirmation before stack deletion
- Optional snapshot deletion

## Resources Deleted

✓ **RDS PostgreSQL Database** (final snapshot created automatically)
✓ **Lambda Functions** (all three: inbound, outbound, transform)
✓ **API Gateway** (REST API and all endpoints)
✓ **Secrets Manager Secrets** (DB password and API credentials)
✓ **Security Groups** (RDS, Lambda, VPC Endpoint)
✓ **VPC Endpoints** (Secrets Manager, API Gateway)
✓ **IAM Roles** (Lambda execution role)
✓ **CloudWatch Log Groups** (all Lambda logs)

## Cost Considerations

After running the teardown script:

### ✅ No Cost Resources (deleted):
- Lambda functions
- API Gateway
- CloudWatch Logs
- VPC Endpoints
- Security Groups
- IAM Roles

### ⚠️ Potential Ongoing Costs:
1. **RDS Snapshots** - Storage charges apply
   - The script offers to delete these
   - Keep if you need to restore later
   
2. **Secrets Manager** - Recovery period (7-30 days)
   - Secrets are scheduled for deletion, not immediate
   - Minimal cost during recovery period

## Daily Workflow for Sandbox

### Morning (Starting Work):
```bash
# Deploy the stack
aws cloudformation create-stack \
  --stack-name gov-health-athena-stack \
  --template-body file://athenahealth-rds-integration.yaml \
  --parameters file://parameters.json \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Evening (Stopping Work):
```bash
# Tear down the stack
./teardown-stack.sh gov-health-athena-stack us-east-1

# When prompted about snapshots, choose "yes" to delete them
```

## Troubleshooting

### Stack Deletion Fails
If stack deletion fails:
1. Check CloudFormation console for error details
2. Common issues:
   - RDS deletion protection still enabled (script handles this)
   - Dependencies preventing resource deletion
   - IAM permissions issues

### Manual Cleanup
If automatic cleanup fails, delete resources manually:
```bash
# List stack resources
aws cloudformation describe-stack-resources \
  --stack-name gov-health-athena-stack \
  --region us-east-1

# Force delete stack (use with caution)
aws cloudformation delete-stack \
  --stack-name gov-health-athena-stack \
  --region us-east-1
```

### Check for Orphaned Resources
```bash
# Check for leftover RDS instances
aws rds describe-db-instances --region us-east-1

# Check for snapshots
aws rds describe-db-snapshots --region us-east-1

# Check for Lambda functions
aws lambda list-functions --region us-east-1

# Check for API Gateways
aws apigateway get-rest-apis --region us-east-1
```

## Safety Features

Both scripts include:
- ✓ Confirmation prompts before deletion
- ✓ Stack existence verification
- ✓ Progress monitoring
- ✓ Error handling
- ✓ Colored output for clarity
- ✓ Detailed summary of actions taken

## AWS Permissions Required

Your AWS credentials need these permissions:
- `cloudformation:*`
- `rds:ModifyDBInstance`
- `rds:DeleteDBInstance`
- `rds:DescribeDBInstances`
- `rds:DescribeDBSnapshots`
- `rds:DeleteDBSnapshot`
- `lambda:*`
- `apigateway:*`
- `secretsmanager:*`
- `logs:*`
- `ec2:*` (for VPC resources)
- `iam:*` (for role deletion)

## Support

If you encounter issues:
1. Check AWS CloudFormation console for detailed error messages
2. Review CloudWatch Logs for Lambda execution errors
3. Verify AWS CLI/boto3 configuration
4. Ensure credentials have sufficient permissions

## Alternative: AWS Console

You can also delete the stack from AWS Console:
1. Go to CloudFormation console
2. Select your stack
3. Click "Delete"
4. Manually disable RDS deletion protection first if needed

However, the scripts automate this process and handle edge cases.
