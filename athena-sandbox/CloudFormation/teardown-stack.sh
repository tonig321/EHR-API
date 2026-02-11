#!/bin/bash

################################################################################
# CloudFormation Stack Teardown Script
# 
# This script safely deletes the AthenaHealth integration stack and handles
# resources that need manual cleanup before stack deletion.
#
# Usage: ./teardown-stack.sh <stack-name> <region>
# Example: ./teardown-stack.sh gov-health-athena-stack us-east-1
################################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check arguments
if [ "$#" -ne 2 ]; then
    echo -e "${RED}Usage: $0 <stack-name> <region>${NC}"
    echo "Example: $0 gov-health-athena-stack us-east-1"
    exit 1
fi

STACK_NAME=$1
REGION=$2

echo -e "${YELLOW}=====================================${NC}"
echo -e "${YELLOW}CloudFormation Stack Teardown${NC}"
echo -e "${YELLOW}=====================================${NC}"
echo "Stack Name: $STACK_NAME"
echo "Region: $REGION"
echo ""

# Function to check if stack exists
check_stack_exists() {
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --output json > /dev/null 2>&1
    return $?
}

# Check if stack exists
if ! check_stack_exists; then
    echo -e "${RED}Stack '$STACK_NAME' not found in region '$REGION'${NC}"
    exit 1
fi

echo -e "${GREEN}Stack found. Beginning teardown process...${NC}"
echo ""

# Step 1: Disable RDS deletion protection
echo -e "${YELLOW}Step 1: Disabling RDS deletion protection...${NC}"
DB_INSTANCE_ID=$(aws cloudformation describe-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackResources[?ResourceType=='AWS::RDS::DBInstance'].PhysicalResourceId" \
    --output text)

if [ -n "$DB_INSTANCE_ID" ]; then
    echo "Found RDS instance: $DB_INSTANCE_ID"
    aws rds modify-db-instance \
        --db-instance-identifier "$DB_INSTANCE_ID" \
        --no-deletion-protection \
        --region "$REGION" \
        --apply-immediately > /dev/null 2>&1 || true
    
    echo "Waiting for RDS instance to be available..."
    aws rds wait db-instance-available \
        --db-instance-identifier "$DB_INSTANCE_ID" \
        --region "$REGION" || true
    
    echo -e "${GREEN}RDS deletion protection disabled${NC}"
else
    echo "No RDS instance found"
fi
echo ""

# Step 2: Empty and delete CloudWatch log groups (optional, as they'll be deleted with stack)
echo -e "${YELLOW}Step 2: Checking CloudWatch Log Groups...${NC}"
LOG_GROUPS=$(aws cloudformation describe-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackResources[?ResourceType=='AWS::Logs::LogGroup'].PhysicalResourceId" \
    --output text)

if [ -n "$LOG_GROUPS" ]; then
    echo "Found log groups: $LOG_GROUPS"
    echo -e "${GREEN}Log groups will be deleted with stack${NC}"
else
    echo "No log groups found"
fi
echo ""

# Step 3: Delete stack
echo -e "${YELLOW}Step 3: Deleting CloudFormation stack...${NC}"
echo -e "${RED}WARNING: This will delete all resources including:${NC}"
echo "  - RDS Database (a final snapshot will be created)"
echo "  - Lambda Functions"
echo "  - API Gateway"
echo "  - Secrets Manager secrets"
echo "  - Security Groups"
echo "  - VPC Endpoints"
echo "  - IAM Roles"
echo ""

read -p "Are you sure you want to continue? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo -e "${YELLOW}Teardown cancelled${NC}"
    exit 0
fi

echo "Initiating stack deletion..."
aws cloudformation delete-stack \
    --stack-name "$STACK_NAME" \
    --region "$REGION"

echo "Waiting for stack deletion to complete..."
echo "This may take 10-15 minutes..."

# Wait for stack deletion with progress updates
WAIT_COUNT=0
while check_stack_exists; do
    STACK_STATUS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query "Stacks[0].StackStatus" \
        --output text 2>/dev/null || echo "DELETE_COMPLETE")
    
    if [ "$STACK_STATUS" == "DELETE_FAILED" ]; then
        echo -e "${RED}Stack deletion failed!${NC}"
        echo "Check the CloudFormation console for details."
        exit 1
    fi
    
    if [ "$STACK_STATUS" == "DELETE_COMPLETE" ]; then
        break
    fi
    
    WAIT_COUNT=$((WAIT_COUNT + 1))
    echo "Status: $STACK_STATUS (waited ${WAIT_COUNT}0 seconds)"
    sleep 10
done

echo -e "${GREEN}Stack deletion complete!${NC}"
echo ""

# Step 4: Clean up orphaned resources (if any)
echo -e "${YELLOW}Step 4: Checking for orphaned resources...${NC}"

# Check for orphaned DB snapshots
SNAPSHOTS=$(aws rds describe-db-snapshots \
    --region "$REGION" \
    --query "DBSnapshots[?contains(DBSnapshotIdentifier, '$DB_INSTANCE_ID')].DBSnapshotIdentifier" \
    --output text 2>/dev/null || echo "")

if [ -n "$SNAPSHOTS" ]; then
    echo -e "${YELLOW}Found DB snapshots:${NC}"
    echo "$SNAPSHOTS"
    read -p "Do you want to delete these snapshots? (yes/no): " DELETE_SNAPSHOTS
    if [ "$DELETE_SNAPSHOTS" == "yes" ]; then
        for SNAPSHOT in $SNAPSHOTS; do
            echo "Deleting snapshot: $SNAPSHOT"
            aws rds delete-db-snapshot \
                --db-snapshot-identifier "$SNAPSHOT" \
                --region "$REGION" > /dev/null 2>&1 || true
        done
        echo -e "${GREEN}Snapshots deleted${NC}"
    fi
else
    echo "No orphaned snapshots found"
fi
echo ""

# Check for orphaned secrets (with deletion protection)
echo -e "${YELLOW}Note: Secrets Manager secrets have a recovery window.${NC}"
echo "They will be permanently deleted after 7-30 days."
echo ""

echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}Teardown Complete!${NC}"
echo -e "${GREEN}=====================================${NC}"
echo ""
echo "Summary:"
echo "  ✓ Stack deleted"
echo "  ✓ RDS database deleted (snapshot created)"
echo "  ✓ All Lambda functions removed"
echo "  ✓ API Gateway deleted"
echo "  ✓ VPC endpoints removed"
echo "  ✓ Security groups deleted"
echo ""
echo -e "${YELLOW}Remember:${NC}"
echo "  - DB snapshots may still incur storage costs"
echo "  - Secrets are in recovery period (can be restored)"
echo "  - CloudWatch logs are deleted"
echo ""
