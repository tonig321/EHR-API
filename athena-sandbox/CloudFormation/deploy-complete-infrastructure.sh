#!/bin/bash

################################################################################
# Master CloudFormation Deployment Script
# 
# This script deploys the complete AthenaHealth integration infrastructure:
# 1. Foundation stack (VPC, KMS, S3, Security Groups, CloudTrail, Config)
# 2. Integration stack (RDS, Lambda, API Gateway, VPC Endpoints)
#
# Usage: ./deploy-complete-infrastructure.sh <region> [key-pair-name]
# Example: ./deploy-complete-infrastructure.sh us-east-1 my-keypair
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
FOUNDATION_TEMPLATE="AthenaAWS-Sandbox-CloudFormationTemplate.yaml"
INTEGRATION_TEMPLATE="athenahealth-rds-integration.yaml"

# Check arguments
if [ "$#" -lt 1 ]; then
    echo -e "${RED}Usage: $0 <region> [key-pair-name]${NC}"
    echo "Example: $0 us-east-1 my-keypair"
    exit 1
fi

REGION=$1
KEY_PAIR_NAME=${2:-""}

echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}AWS Infrastructure Deployment${NC}"
echo -e "${BLUE}=====================================${NC}"
echo "Environment: $ENVIRONMENT_NAME"
echo "Region: $REGION"
echo "Foundation Stack: $FOUNDATION_STACK_NAME"
echo "Integration Stack: $INTEGRATION_STACK_NAME"
if [ -n "$KEY_PAIR_NAME" ]; then
    echo "Key Pair: $KEY_PAIR_NAME"
fi
echo ""

# Function to check if a file exists
check_file_exists() {
    if [ ! -f "$1" ]; then
        echo -e "${RED}Error: Template file '$1' not found${NC}"
        echo "Please ensure the template files are in the current directory:"
        echo "  - $FOUNDATION_TEMPLATE"
        echo "  - $INTEGRATION_TEMPLATE"
        exit 1
    fi
}

# Function to check if stack exists
check_stack_exists() {
    aws cloudformation describe-stacks \
        --stack-name "$1" \
        --region "$2" \
        --output json > /dev/null 2>&1
    return $?
}

# Function to wait for stack operation
wait_for_stack() {
    local stack_name=$1
    local region=$2
    local operation=$3  # CREATE or UPDATE
    
    echo "Waiting for stack $operation to complete..."
    local wait_count=0
    local max_wait=120  # 20 minutes max
    
    while true; do
        if ! check_stack_exists "$stack_name" "$region"; then
            if [ "$operation" == "CREATE" ]; then
                echo -e "${RED}Stack creation failed - stack not found${NC}"
                return 1
            fi
        fi
        
        STATUS=$(aws cloudformation describe-stacks \
            --stack-name "$stack_name" \
            --region "$region" \
            --query "Stacks[0].StackStatus" \
            --output text 2>/dev/null || echo "UNKNOWN")
        
        case $STATUS in
            CREATE_COMPLETE|UPDATE_COMPLETE)
                echo -e "${GREEN}Stack $operation completed successfully!${NC}"
                return 0
                ;;
            CREATE_FAILED|ROLLBACK_COMPLETE|ROLLBACK_FAILED|UPDATE_ROLLBACK_COMPLETE|UPDATE_ROLLBACK_FAILED)
                echo -e "${RED}Stack $operation failed with status: $STATUS${NC}"
                echo "Check CloudFormation console for detailed error information"
                return 1
                ;;
            CREATE_IN_PROGRESS|UPDATE_IN_PROGRESS|UPDATE_COMPLETE_CLEANUP_IN_PROGRESS)
                wait_count=$((wait_count + 1))
                if [ $wait_count -ge $max_wait ]; then
                    echo -e "${RED}Timeout waiting for stack $operation${NC}"
                    return 1
                fi
                echo "Status: $STATUS (waited ${wait_count}0 seconds)"
                sleep 10
                ;;
            *)
                echo "Status: $STATUS"
                sleep 10
                ;;
        esac
    done
}

# Check template files exist
echo -e "${YELLOW}Step 1: Validating template files...${NC}"
check_file_exists "$FOUNDATION_TEMPLATE"
check_file_exists "$INTEGRATION_TEMPLATE"
echo -e "${GREEN}✓ Template files found${NC}"
echo ""

# Validate templates
echo -e "${YELLOW}Step 2: Validating CloudFormation templates...${NC}"
echo "Validating foundation template..."
aws cloudformation validate-template \
    --template-body file://"$FOUNDATION_TEMPLATE" \
    --region "$REGION" > /dev/null
echo -e "${GREEN}✓ Foundation template is valid${NC}"

echo "Validating integration template..."
aws cloudformation validate-template \
    --template-body file://"$INTEGRATION_TEMPLATE" \
    --region "$REGION" > /dev/null
echo -e "${GREEN}✓ Integration template is valid${NC}"
echo ""

# Deploy Foundation Stack
echo -e "${YELLOW}Step 3: Deploying foundation stack...${NC}"
if check_stack_exists "$FOUNDATION_STACK_NAME" "$REGION"; then
    echo -e "${YELLOW}Foundation stack already exists${NC}"
    read -p "Do you want to update it? (yes/no): " UPDATE_FOUNDATION
    if [ "$UPDATE_FOUNDATION" == "yes" ]; then
        if [ -n "$KEY_PAIR_NAME" ]; then
            aws cloudformation update-stack \
                --stack-name "$FOUNDATION_STACK_NAME" \
                --template-body file://"$FOUNDATION_TEMPLATE" \
                --parameters ParameterKey=KeyPairName,ParameterValue="$KEY_PAIR_NAME" \
                --capabilities CAPABILITY_IAM \
                --region "$REGION"
        else
            aws cloudformation update-stack \
                --stack-name "$FOUNDATION_STACK_NAME" \
                --template-body file://"$FOUNDATION_TEMPLATE" \
                --capabilities CAPABILITY_IAM \
                --region "$REGION"
        fi
        wait_for_stack "$FOUNDATION_STACK_NAME" "$REGION" "UPDATE"
    fi
else
    if [ -n "$KEY_PAIR_NAME" ]; then
        aws cloudformation create-stack \
            --stack-name "$FOUNDATION_STACK_NAME" \
            --template-body file://"$FOUNDATION_TEMPLATE" \
            --parameters ParameterKey=KeyPairName,ParameterValue="$KEY_PAIR_NAME" \
            --capabilities CAPABILITY_IAM \
            --region "$REGION"
    else
        aws cloudformation create-stack \
            --stack-name "$FOUNDATION_STACK_NAME" \
            --template-body file://"$FOUNDATION_TEMPLATE" \
            --capabilities CAPABILITY_IAM \
            --region "$REGION"
    fi
    
    if ! wait_for_stack "$FOUNDATION_STACK_NAME" "$REGION" "CREATE"; then
        echo -e "${RED}Foundation stack deployment failed${NC}"
        exit 1
    fi
fi
echo ""

# Get foundation stack outputs
echo -e "${YELLOW}Step 4: Retrieving foundation stack outputs...${NC}"
VPC_ID=$(aws cloudformation describe-stacks \
    --stack-name "$FOUNDATION_STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='VPCId'].OutputValue" \
    --output text)

PRIVATE_SUBNET_1=$(aws cloudformation describe-stacks \
    --stack-name "$FOUNDATION_STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='PrivateSubnet1Id'].OutputValue" \
    --output text)

PRIVATE_SUBNET_2=$(aws cloudformation describe-stacks \
    --stack-name "$FOUNDATION_STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='PrivateSubnet2Id'].OutputValue" \
    --output text)

KMS_KEY_ID=$(aws cloudformation describe-stacks \
    --stack-name "$FOUNDATION_STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='KMSKeyId'].OutputValue" \
    --output text)

echo "VPC ID: $VPC_ID"
echo "Private Subnet 1: $PRIVATE_SUBNET_1"
echo "Private Subnet 2: $PRIVATE_SUBNET_2"
echo "KMS Key ID: $KMS_KEY_ID"
echo -e "${GREEN}✓ Foundation outputs retrieved${NC}"
echo ""

# Deploy Integration Stack
echo -e "${YELLOW}Step 5: Deploying integration stack...${NC}"
if check_stack_exists "$INTEGRATION_STACK_NAME" "$REGION"; then
    echo -e "${YELLOW}Integration stack already exists${NC}"
    read -p "Do you want to update it? (yes/no): " UPDATE_INTEGRATION
    if [ "$UPDATE_INTEGRATION" == "yes" ]; then
        aws cloudformation update-stack \
            --stack-name "$INTEGRATION_STACK_NAME" \
            --template-body file://"$INTEGRATION_TEMPLATE" \
            --parameters \
                ParameterKey=VPCId,ParameterValue="$VPC_ID" \
                ParameterKey=PrivateSubnet1Id,ParameterValue="$PRIVATE_SUBNET_1" \
                ParameterKey=PrivateSubnet2Id,ParameterValue="$PRIVATE_SUBNET_2" \
                ParameterKey=KMSKeyId,ParameterValue="$KMS_KEY_ID" \
            --capabilities CAPABILITY_NAMED_IAM \
            --region "$REGION"
        wait_for_stack "$INTEGRATION_STACK_NAME" "$REGION" "UPDATE"
    fi
else
    aws cloudformation create-stack \
        --stack-name "$INTEGRATION_STACK_NAME" \
        --template-body file://"$INTEGRATION_TEMPLATE" \
        --parameters \
            ParameterKey=VPCId,ParameterValue="$VPC_ID" \
            ParameterKey=PrivateSubnet1Id,ParameterValue="$PRIVATE_SUBNET_1" \
            ParameterKey=PrivateSubnet2Id,ParameterValue="$PRIVATE_SUBNET_2" \
            ParameterKey=KMSKeyId,ParameterValue="$KMS_KEY_ID" \
        --capabilities CAPABILITY_NAMED_IAM \
        --region "$REGION"
    
    if ! wait_for_stack "$INTEGRATION_STACK_NAME" "$REGION" "CREATE"; then
        echo -e "${RED}Integration stack deployment failed${NC}"
        exit 1
    fi
fi
echo ""

# Get integration stack outputs
echo -e "${YELLOW}Step 6: Retrieving integration stack outputs...${NC}"
RDS_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name "$INTEGRATION_STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='RDSEndpoint'].OutputValue" \
    --output text 2>/dev/null || echo "N/A")

API_GATEWAY_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name "$INTEGRATION_STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='APIGatewayEndpoint'].OutputValue" \
    --output text 2>/dev/null || echo "N/A")

echo "RDS Endpoint: $RDS_ENDPOINT"
echo "API Gateway Endpoint: $API_GATEWAY_ENDPOINT"
echo ""

# Final summary
echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}=====================================${NC}"
echo ""
echo "Infrastructure Summary:"
echo "  ✓ Foundation Stack: $FOUNDATION_STACK_NAME"
echo "  ✓ Integration Stack: $INTEGRATION_STACK_NAME"
echo ""
echo "Key Resources:"
echo "  - VPC ID: $VPC_ID"
echo "  - RDS Endpoint: $RDS_ENDPOINT"
echo "  - API Gateway: $API_GATEWAY_ENDPOINT"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Update AthenaHealth API credentials in Secrets Manager"
echo "2. Configure Lambda functions with your business logic"
echo "3. Initialize the RDS database schema"
echo "4. Test the integration endpoints"
echo ""
echo -e "${YELLOW}To tear down this infrastructure:${NC}"
echo "./teardown-complete-infrastructure.sh $REGION"
echo ""
