#!/bin/bash

################################################################################
# Master CloudFormation Teardown Script
# 
# This script safely deletes the complete AthenaHealth integration infrastructure:
# 1. Integration stack (RDS, Lambda, API Gateway, VPC Endpoints) - FIRST
# 2. Foundation stack (VPC, KMS, S3, Security Groups) - SECOND
#
# Usage: ./teardown-complete-infrastructure.sh <region>
# Example: ./teardown-complete-infrastructure.sh us-east-1
################################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT_NAME="gov-health"
FOUNDATION_STACK_NAME="${ENVIRONMENT_NAME}-foundation"
INTEGRATION_STACK_NAME="${ENVIRONMENT_NAME}-integration"

# Check arguments
if [ "$#" -ne 1 ]; then
    echo -e "${RED}Usage: $0 <region>${NC}"
    echo "Example: $0 us-east-1"
    exit 1
fi

REGION=$1

echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}AWS Infrastructure Teardown${NC}"
echo -e "${BLUE}=====================================${NC}"
echo "Environment: $ENVIRONMENT_NAME"
echo "Region: $REGION"
echo "Integration Stack: $INTEGRATION_STACK_NAME"
echo "Foundation Stack: $FOUNDATION_STACK_NAME"
echo ""

# Function to check if stack exists
check_stack_exists() {
    aws cloudformation describe-stacks \
        --stack-name "$1" \
        --region "$2" \
        --output json > /dev/null 2>&1
    return $?
}

# Function to get stack resources
get_stack_resources() {
    local stack_name=$1
    local region=$2
    local resource_type=$3
    
    aws cloudformation describe-stack-resources \
        --stack-name "$stack_name" \
        --region "$region" \
        --query "StackResources[?ResourceType=='$resource_type'].PhysicalResourceId" \
        --output text 2>/dev/null || echo ""
}

# Function to wait for stack deletion
wait_for_stack_deletion() {
    local stack_name=$1
    local region=$2
    
    echo "Waiting for stack deletion to complete..."
    local wait_count=0
    local max_wait=120  # 20 minutes max
    
    while check_stack_exists "$stack_name" "$region"; do
        STATUS=$(aws cloudformation describe-stacks \
            --stack-name "$stack_name" \
            --region "$region" \
            --query "Stacks[0].StackStatus" \
            --output text 2>/dev/null || echo "DELETE_COMPLETE")
        
        if [ "$STATUS" == "DELETE_FAILED" ]; then
            echo -e "${RED}Stack deletion failed!${NC}"
            echo "Check the CloudFormation console for details."
            return 1
        fi
        
        if [ "$STATUS" == "DELETE_COMPLETE" ]; then
            break
        fi
        
        wait_count=$((wait_count + 1))
        if [ $wait_count -ge $max_wait ]; then
            echo -e "${RED}Timeout waiting for stack deletion${NC}"
            return 1
        fi
        
        echo "Status: $STATUS (waited ${wait_count}0 seconds)"
        sleep 10
    done
    
    echo -e "${GREEN}Stack deletion complete!${NC}"
    return 0
}

# Display warning
echo -e "${RED}WARNING: This will delete ALL resources including:${NC}"
echo ""
echo "Integration Stack:"
echo "  - RDS Database (snapshot will be created)"
echo "  - Lambda Functions (3)"
echo "  - API Gateway"
echo "  - Secrets Manager secrets"
echo "  - VPC Endpoints"
echo ""
echo "Foundation Stack:"
echo "  - VPC and all subnets"
echo "  - NAT Gateway and Internet Gateway"
echo "  - S3 Buckets (PHI data and logs)"
echo "  - KMS Keys"
echo "  - Security Groups"
echo "  - CloudTrail"
echo "  - Config Service"
echo ""

read -p "Are you sure you want to continue? Type 'DELETE' to confirm: " CONFIRM
if [ "$CONFIRM" != "DELETE" ]; then
    echo -e "${YELLOW}Teardown cancelled${NC}"
    exit 0
fi
echo ""

# ============================================================================
# STEP 1: Delete Integration Stack
# ============================================================================
echo -e "${YELLOW}Step 1: Preparing integration stack for deletion...${NC}"

if check_stack_exists "$INTEGRATION_STACK_NAME" "$REGION"; then
    # Disable RDS deletion protection
    echo "Disabling RDS deletion protection..."
    DB_INSTANCE_ID=$(get_stack_resources "$INTEGRATION_STACK_NAME" "$REGION" "AWS::RDS::DBInstance")
    
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
            --region "$REGION" 2>/dev/null || true
        
        echo -e "${GREEN}✓ RDS deletion protection disabled${NC}"
    else
        echo "No RDS instance found"
    fi
    
    echo ""
    echo "Deleting integration stack..."
    aws cloudformation delete-stack \
        --stack-name "$INTEGRATION_STACK_NAME" \
        --region "$REGION"
    
    if ! wait_for_stack_deletion "$INTEGRATION_STACK_NAME" "$REGION"; then
        echo -e "${RED}Failed to delete integration stack${NC}"
        exit 1
    fi
    echo ""
else
    echo -e "${YELLOW}Integration stack not found, skipping...${NC}"
    echo ""
fi

# ============================================================================
# STEP 2: Delete Foundation Stack
# ============================================================================
echo -e "${YELLOW}Step 2: Preparing foundation stack for deletion...${NC}"

if check_stack_exists "$FOUNDATION_STACK_NAME" "$REGION"; then
    # Empty S3 buckets before stack deletion
    echo "Checking for S3 buckets..."
    PHI_BUCKET=$(get_stack_resources "$FOUNDATION_STACK_NAME" "$REGION" "AWS::S3::Bucket" | grep phi || echo "")
    LOG_BUCKET=$(get_stack_resources "$FOUNDATION_STACK_NAME" "$REGION" "AWS::S3::Bucket" | grep logs || echo "")
    
    if [ -n "$PHI_BUCKET" ]; then
        echo "Found PHI bucket: $PHI_BUCKET"
        read -p "Empty PHI bucket? (yes/no): " EMPTY_PHI
        if [ "$EMPTY_PHI" == "yes" ]; then
            echo "Emptying PHI bucket..."
            aws s3 rm s3://"$PHI_BUCKET" --recursive --region "$REGION" 2>/dev/null || true
            # Delete all versions and delete markers
            aws s3api list-object-versions \
                --bucket "$PHI_BUCKET" \
                --region "$REGION" \
                --query 'Versions[].{Key:Key,VersionId:VersionId}' \
                --output json 2>/dev/null | \
            jq -r '.[] | "--key \(.Key) --version-id \(.VersionId)"' | \
            xargs -I {} aws s3api delete-object --bucket "$PHI_BUCKET" --region "$REGION" {} 2>/dev/null || true
            
            aws s3api list-object-versions \
                --bucket "$PHI_BUCKET" \
                --region "$REGION" \
                --query 'DeleteMarkers[].{Key:Key,VersionId:VersionId}' \
                --output json 2>/dev/null | \
            jq -r '.[] | "--key \(.Key) --version-id \(.VersionId)"' | \
            xargs -I {} aws s3api delete-object --bucket "$PHI_BUCKET" --region "$REGION" {} 2>/dev/null || true
            
            echo -e "${GREEN}✓ PHI bucket emptied${NC}"
        fi
    fi
    
    if [ -n "$LOG_BUCKET" ]; then
        echo "Found log bucket: $LOG_BUCKET"
        read -p "Empty log bucket? (yes/no): " EMPTY_LOGS
        if [ "$EMPTY_LOGS" == "yes" ]; then
            echo "Emptying log bucket..."
            aws s3 rm s3://"$LOG_BUCKET" --recursive --region "$REGION" 2>/dev/null || true
            echo -e "${GREEN}✓ Log bucket emptied${NC}"
        fi
    fi
    
    echo ""
    echo "Deleting foundation stack..."
    aws cloudformation delete-stack \
        --stack-name "$FOUNDATION_STACK_NAME" \
        --region "$REGION"
    
    if ! wait_for_stack_deletion "$FOUNDATION_STACK_NAME" "$REGION"; then
        echo -e "${RED}Failed to delete foundation stack${NC}"
        exit 1
    fi
    echo ""
else
    echo -e "${YELLOW}Foundation stack not found, skipping...${NC}"
    echo ""
fi

# ============================================================================
# STEP 3: Clean up orphaned resources
# ============================================================================
echo -e "${YELLOW}Step 3: Checking for orphaned resources...${NC}"

# Check for RDS snapshots
if [ -n "$DB_INSTANCE_ID" ]; then
    SNAPSHOTS=$(aws rds describe-db-snapshots \
        --region "$REGION" \
        --query "DBSnapshots[?contains(DBSnapshotIdentifier, '$DB_INSTANCE_ID')].DBSnapshotIdentifier" \
        --output text 2>/dev/null || echo "")
    
    if [ -n "$SNAPSHOTS" ]; then
        echo -e "${YELLOW}Found DB snapshots:${NC}"
        echo "$SNAPSHOTS"
        read -p "Delete these snapshots? (yes/no): " DELETE_SNAPSHOTS
        if [ "$DELETE_SNAPSHOTS" == "yes" ]; then
            for SNAPSHOT in $SNAPSHOTS; do
                echo "Deleting snapshot: $SNAPSHOT"
                aws rds delete-db-snapshot \
                    --db-snapshot-identifier "$SNAPSHOT" \
                    --region "$REGION" > /dev/null 2>&1 || true
            done
            echo -e "${GREEN}✓ Snapshots deleted${NC}"
        fi
    else
        echo "No orphaned snapshots found"
    fi
fi

# Check for orphaned S3 buckets (if deletion failed)
echo ""
echo "Checking for orphaned S3 buckets..."
if [ -n "$PHI_BUCKET" ]; then
    if aws s3 ls "s3://$PHI_BUCKET" --region "$REGION" > /dev/null 2>&1; then
        echo -e "${YELLOW}Warning: PHI bucket still exists: $PHI_BUCKET${NC}"
        echo "Manual deletion may be required"
    fi
fi

if [ -n "$LOG_BUCKET" ]; then
    if aws s3 ls "s3://$LOG_BUCKET" --region "$REGION" > /dev/null 2>&1; then
        echo -e "${YELLOW}Warning: Log bucket still exists: $LOG_BUCKET${NC}"
        echo "Manual deletion may be required"
    fi
fi

echo ""
echo -e "${YELLOW}Note about Secrets Manager:${NC}"
echo "Secrets have a recovery window of 7-30 days before permanent deletion."
echo ""

# Final summary
echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}Teardown Complete!${NC}"
echo -e "${GREEN}=====================================${NC}"
echo ""
echo "Summary:"
echo "  ✓ Integration stack deleted"
echo "  ✓ Foundation stack deleted"
echo "  ✓ RDS database deleted (snapshot may exist)"
echo "  ✓ Lambda functions removed"
echo "  ✓ API Gateway deleted"
echo "  ✓ VPC and networking deleted"
echo ""
echo -e "${YELLOW}Potential remaining costs:${NC}"
echo "  - RDS snapshots (storage)"
echo "  - S3 buckets (if not emptied)"
echo "  - Secrets Manager (recovery period)"
echo ""
echo -e "${YELLOW}To verify complete cleanup:${NC}"
echo "aws cloudformation list-stacks --region $REGION --query \"StackSummaries[?contains(StackName,'$ENVIRONMENT_NAME')]\""
echo ""
