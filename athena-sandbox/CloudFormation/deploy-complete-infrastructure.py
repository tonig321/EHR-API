#!/usr/bin/env python3
"""
Master CloudFormation Deployment Script (Python version)

This script deploys the complete AthenaHealth integration infrastructure:
1. Foundation stack (VPC, KMS, S3, Security Groups, CloudTrail, Config)
2. Integration stack (RDS, Lambda, API Gateway, VPC Endpoints)

Usage: python deploy-complete-infrastructure.py <region> [key-pair-name]
Example: python deploy-complete-infrastructure.py us-east-1 my-keypair
"""

import sys
import time
import boto3
from botocore.exceptions import ClientError

# Color codes
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

# Configuration
ENVIRONMENT_NAME = "gov-health"
FOUNDATION_STACK_NAME = f"{ENVIRONMENT_NAME}-foundation"
INTEGRATION_STACK_NAME = f"{ENVIRONMENT_NAME}-integration"
FOUNDATION_TEMPLATE = "AthenaAWS-Sandbox-CloudFormationTemplate.yaml"
INTEGRATION_TEMPLATE = "athenahealth-rds-integration.yaml"

def print_color(message, color):
    """Print colored message"""
    print(f"{color}{message}{Colors.NC}")

def check_file_exists(filename):
    """Check if template file exists"""
    import os
    if not os.path.exists(filename):
        print_color(f"Error: Template file '{filename}' not found", Colors.RED)
        print("Please ensure the template files are in the current directory:")
        print(f"  - {FOUNDATION_TEMPLATE}")
        print(f"  - {INTEGRATION_TEMPLATE}")
        sys.exit(1)

def check_stack_exists(cf_client, stack_name):
    """Check if CloudFormation stack exists"""
    try:
        cf_client.describe_stacks(StackName=stack_name)
        return True
    except ClientError as e:
        if 'does not exist' in str(e):
            return False
        raise

def validate_template(cf_client, template_file):
    """Validate CloudFormation template"""
    with open(template_file, 'r') as f:
        template_body = f.read()
    
    try:
        cf_client.validate_template(TemplateBody=template_body)
        return True
    except ClientError as e:
        print_color(f"Template validation failed: {e}", Colors.RED)
        return False

def wait_for_stack_operation(cf_client, stack_name, operation):
    """Wait for stack CREATE or UPDATE to complete"""
    print(f"Waiting for stack {operation} to complete...")
    wait_count = 0
    max_wait = 120  # 20 minutes
    
    while True:
        try:
            response = cf_client.describe_stacks(StackName=stack_name)
            status = response['Stacks'][0]['StackStatus']
            
            if status in ['CREATE_COMPLETE', 'UPDATE_COMPLETE']:
                print_color(f"Stack {operation} completed successfully!", Colors.GREEN)
                return True
            
            if status in ['CREATE_FAILED', 'ROLLBACK_COMPLETE', 'ROLLBACK_FAILED',
                         'UPDATE_ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_FAILED']:
                print_color(f"Stack {operation} failed with status: {status}", Colors.RED)
                print("Check CloudFormation console for detailed error information")
                return False
            
            if status in ['CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS', 
                         'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS']:
                wait_count += 1
                if wait_count >= max_wait:
                    print_color(f"Timeout waiting for stack {operation}", Colors.RED)
                    return False
                print(f"Status: {status} (waited {wait_count * 10} seconds)")
                time.sleep(10)
            else:
                print(f"Status: {status}")
                time.sleep(10)
                
        except ClientError as e:
            if 'does not exist' in str(e) and operation == "CREATE":
                print_color("Stack creation failed - stack not found", Colors.RED)
                return False
            raise

def get_stack_output(cf_client, stack_name, output_key):
    """Get a specific output value from a stack"""
    try:
        response = cf_client.describe_stacks(StackName=stack_name)
        outputs = response['Stacks'][0].get('Outputs', [])
        for output in outputs:
            if output['OutputKey'] == output_key:
                return output['OutputValue']
        return None
    except ClientError:
        return None

def deploy_foundation_stack(cf_client, region, key_pair_name=None):
    """Deploy the foundation stack"""
    print_color("Step 3: Deploying foundation stack...", Colors.YELLOW)
    
    with open(FOUNDATION_TEMPLATE, 'r') as f:
        template_body = f.read()
    
    parameters = []
    if key_pair_name:
        parameters.append({
            'ParameterKey': 'KeyPairName',
            'ParameterValue': key_pair_name
        })
    
    if check_stack_exists(cf_client, FOUNDATION_STACK_NAME):
        print_color("Foundation stack already exists", Colors.YELLOW)
        update = input("Do you want to update it? (yes/no): ")
        if update.lower() == 'yes':
            try:
                cf_client.update_stack(
                    StackName=FOUNDATION_STACK_NAME,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_IAM']
                )
                return wait_for_stack_operation(cf_client, FOUNDATION_STACK_NAME, "UPDATE")
            except ClientError as e:
                if 'No updates are to be performed' in str(e):
                    print_color("No updates needed", Colors.GREEN)
                    return True
                raise
        return True
    else:
        cf_client.create_stack(
            StackName=FOUNDATION_STACK_NAME,
            TemplateBody=template_body,
            Parameters=parameters,
            Capabilities=['CAPABILITY_IAM']
        )
        return wait_for_stack_operation(cf_client, FOUNDATION_STACK_NAME, "CREATE")

def deploy_integration_stack(cf_client, vpc_id, subnet1_id, subnet2_id, kms_key_id):
    """Deploy the integration stack"""
    print_color("Step 5: Deploying integration stack...", Colors.YELLOW)
    
    with open(INTEGRATION_TEMPLATE, 'r') as f:
        template_body = f.read()
    
    parameters = [
        {'ParameterKey': 'VPCId', 'ParameterValue': vpc_id},
        {'ParameterKey': 'PrivateSubnet1Id', 'ParameterValue': subnet1_id},
        {'ParameterKey': 'PrivateSubnet2Id', 'ParameterValue': subnet2_id},
        {'ParameterKey': 'KMSKeyId', 'ParameterValue': kms_key_id}
    ]
    
    if check_stack_exists(cf_client, INTEGRATION_STACK_NAME):
        print_color("Integration stack already exists", Colors.YELLOW)
        update = input("Do you want to update it? (yes/no): ")
        if update.lower() == 'yes':
            try:
                cf_client.update_stack(
                    StackName=INTEGRATION_STACK_NAME,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_NAMED_IAM']
                )
                return wait_for_stack_operation(cf_client, INTEGRATION_STACK_NAME, "UPDATE")
            except ClientError as e:
                if 'No updates are to be performed' in str(e):
                    print_color("No updates needed", Colors.GREEN)
                    return True
                raise
        return True
    else:
        cf_client.create_stack(
            StackName=INTEGRATION_STACK_NAME,
            TemplateBody=template_body,
            Parameters=parameters,
            Capabilities=['CAPABILITY_NAMED_IAM']
        )
        return wait_for_stack_operation(cf_client, INTEGRATION_STACK_NAME, "CREATE")

def main():
    """Main deployment function"""
    if len(sys.argv) < 2:
        print_color("Usage: python deploy-complete-infrastructure.py <region> [key-pair-name]", Colors.RED)
        print("Example: python deploy-complete-infrastructure.py us-east-1 my-keypair")
        sys.exit(1)
    
    region = sys.argv[1]
    key_pair_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    print_color("=" * 40, Colors.BLUE)
    print_color("AWS Infrastructure Deployment", Colors.BLUE)
    print_color("=" * 40, Colors.BLUE)
    print(f"Environment: {ENVIRONMENT_NAME}")
    print(f"Region: {region}")
    print(f"Foundation Stack: {FOUNDATION_STACK_NAME}")
    print(f"Integration Stack: {INTEGRATION_STACK_NAME}")
    if key_pair_name:
        print(f"Key Pair: {key_pair_name}")
    print()
    
    # Initialize AWS client
    try:
        cf_client = boto3.client('cloudformation', region_name=region)
    except Exception as e:
        print_color(f"Error initializing AWS client: {e}", Colors.RED)
        sys.exit(1)
    
    # Step 1: Check template files
    print_color("Step 1: Validating template files...", Colors.YELLOW)
    check_file_exists(FOUNDATION_TEMPLATE)
    check_file_exists(INTEGRATION_TEMPLATE)
    print_color("✓ Template files found", Colors.GREEN)
    print()
    
    # Step 2: Validate templates
    print_color("Step 2: Validating CloudFormation templates...", Colors.YELLOW)
    print("Validating foundation template...")
    if not validate_template(cf_client, FOUNDATION_TEMPLATE):
        sys.exit(1)
    print_color("✓ Foundation template is valid", Colors.GREEN)
    
    print("Validating integration template...")
    if not validate_template(cf_client, INTEGRATION_TEMPLATE):
        sys.exit(1)
    print_color("✓ Integration template is valid", Colors.GREEN)
    print()
    
    # Step 3: Deploy foundation stack
    if not deploy_foundation_stack(cf_client, region, key_pair_name):
        print_color("Foundation stack deployment failed", Colors.RED)
        sys.exit(1)
    print()
    
    # Step 4: Get foundation stack outputs
    print_color("Step 4: Retrieving foundation stack outputs...", Colors.YELLOW)
    vpc_id = get_stack_output(cf_client, FOUNDATION_STACK_NAME, 'VPCId')
    subnet1_id = get_stack_output(cf_client, FOUNDATION_STACK_NAME, 'PrivateSubnet1Id')
    subnet2_id = get_stack_output(cf_client, FOUNDATION_STACK_NAME, 'PrivateSubnet2Id')
    kms_key_id = get_stack_output(cf_client, FOUNDATION_STACK_NAME, 'KMSKeyId')
    
    print(f"VPC ID: {vpc_id}")
    print(f"Private Subnet 1: {subnet1_id}")
    print(f"Private Subnet 2: {subnet2_id}")
    print(f"KMS Key ID: {kms_key_id}")
    print_color("✓ Foundation outputs retrieved", Colors.GREEN)
    print()
    
    # Step 5: Deploy integration stack
    if not deploy_integration_stack(cf_client, vpc_id, subnet1_id, subnet2_id, kms_key_id):
        print_color("Integration stack deployment failed", Colors.RED)
        sys.exit(1)
    print()
    
    # Step 6: Get integration stack outputs
    print_color("Step 6: Retrieving integration stack outputs...", Colors.YELLOW)
    rds_endpoint = get_stack_output(cf_client, INTEGRATION_STACK_NAME, 'RDSEndpoint') or "N/A"
    api_gateway = get_stack_output(cf_client, INTEGRATION_STACK_NAME, 'APIGatewayEndpoint') or "N/A"
    
    print(f"RDS Endpoint: {rds_endpoint}")
    print(f"API Gateway Endpoint: {api_gateway}")
    print()
    
    # Final summary
    print_color("=" * 40, Colors.GREEN)
    print_color("Deployment Complete!", Colors.GREEN)
    print_color("=" * 40, Colors.GREEN)
    print()
    print("Infrastructure Summary:")
    print(f"  ✓ Foundation Stack: {FOUNDATION_STACK_NAME}")
    print(f"  ✓ Integration Stack: {INTEGRATION_STACK_NAME}")
    print()
    print("Key Resources:")
    print(f"  - VPC ID: {vpc_id}")
    print(f"  - RDS Endpoint: {rds_endpoint}")
    print(f"  - API Gateway: {api_gateway}")
    print()
    print_color("Next Steps:", Colors.YELLOW)
    print("1. Update AthenaHealth API credentials in Secrets Manager")
    print("2. Configure Lambda functions with your business logic")
    print("3. Initialize the RDS database schema")
    print("4. Test the integration endpoints")
    print()
    print_color("To tear down this infrastructure:", Colors.YELLOW)
    print(f"python teardown-complete-infrastructure.py {region}")
    print()

if __name__ == '__main__':
    main()
