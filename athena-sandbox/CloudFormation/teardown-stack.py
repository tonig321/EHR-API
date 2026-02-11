#!/usr/bin/env python3
"""
CloudFormation Stack Teardown Script (Python version)

This script safely deletes the AthenaHealth integration stack and handles
resources that need manual cleanup before stack deletion.

Usage: python teardown-stack.py <stack-name> <region>
Example: python teardown-stack.py gov-health-athena-stack us-east-1
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
    NC = '\033[0m'  # No Color

def print_color(message, color):
    """Print colored message"""
    print(f"{color}{message}{Colors.NC}")

def check_stack_exists(cf_client, stack_name):
    """Check if CloudFormation stack exists"""
    try:
        cf_client.describe_stacks(StackName=stack_name)
        return True
    except ClientError as e:
        if 'does not exist' in str(e):
            return False
        raise

def get_stack_resources(cf_client, stack_name, resource_type):
    """Get physical resource IDs for a specific resource type"""
    try:
        response = cf_client.describe_stack_resources(StackName=stack_name)
        resources = [
            r['PhysicalResourceId'] 
            for r in response['StackResources'] 
            if r['ResourceType'] == resource_type
        ]
        return resources
    except ClientError:
        return []

def disable_rds_deletion_protection(rds_client, db_instance_id):
    """Disable RDS deletion protection"""
    try:
        print(f"Found RDS instance: {db_instance_id}")
        rds_client.modify_db_instance(
            DBInstanceIdentifier=db_instance_id,
            DeletionProtection=False,
            ApplyImmediately=True
        )
        
        print("Waiting for RDS instance to be available...")
        waiter = rds_client.get_waiter('db_instance_available')
        waiter.wait(
            DBInstanceIdentifier=db_instance_id,
            WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
        )
        print_color("RDS deletion protection disabled", Colors.GREEN)
        return True
    except ClientError as e:
        print_color(f"Warning: Could not disable deletion protection: {e}", Colors.YELLOW)
        return False

def delete_stack(cf_client, stack_name):
    """Delete CloudFormation stack"""
    try:
        cf_client.delete_stack(StackName=stack_name)
        print("Initiating stack deletion...")
        print("This may take 10-15 minutes...")
        
        wait_count = 0
        while check_stack_exists(cf_client, stack_name):
            try:
                response = cf_client.describe_stacks(StackName=stack_name)
                status = response['Stacks'][0]['StackStatus']
                
                if status == 'DELETE_FAILED':
                    print_color("Stack deletion failed!", Colors.RED)
                    print("Check the CloudFormation console for details.")
                    return False
                
                if status == 'DELETE_COMPLETE':
                    break
                
                wait_count += 1
                print(f"Status: {status} (waited {wait_count * 10} seconds)")
                time.sleep(10)
                
            except ClientError as e:
                if 'does not exist' in str(e):
                    break
                raise
        
        print_color("Stack deletion complete!", Colors.GREEN)
        return True
        
    except ClientError as e:
        print_color(f"Error deleting stack: {e}", Colors.RED)
        return False

def cleanup_snapshots(rds_client, db_instance_id, region):
    """Clean up RDS snapshots"""
    try:
        response = rds_client.describe_db_snapshots()
        snapshots = [
            s['DBSnapshotIdentifier'] 
            for s in response['DBSnapshots'] 
            if db_instance_id in s['DBSnapshotIdentifier']
        ]
        
        if snapshots:
            print_color("Found DB snapshots:", Colors.YELLOW)
            for snapshot in snapshots:
                print(f"  - {snapshot}")
            
            confirm = input("Do you want to delete these snapshots? (yes/no): ")
            if confirm.lower() == 'yes':
                for snapshot in snapshots:
                    try:
                        print(f"Deleting snapshot: {snapshot}")
                        rds_client.delete_db_snapshot(DBSnapshotIdentifier=snapshot)
                    except ClientError as e:
                        print_color(f"Warning: Could not delete {snapshot}: {e}", Colors.YELLOW)
                print_color("Snapshots deleted", Colors.GREEN)
        else:
            print("No orphaned snapshots found")
            
    except ClientError as e:
        print_color(f"Warning: Could not check for snapshots: {e}", Colors.YELLOW)

def main():
    """Main teardown function"""
    if len(sys.argv) != 3:
        print_color("Usage: python teardown-stack.py <stack-name> <region>", Colors.RED)
        print("Example: python teardown-stack.py gov-health-athena-stack us-east-1")
        sys.exit(1)
    
    stack_name = sys.argv[1]
    region = sys.argv[2]
    
    print_color("=" * 40, Colors.YELLOW)
    print_color("CloudFormation Stack Teardown", Colors.YELLOW)
    print_color("=" * 40, Colors.YELLOW)
    print(f"Stack Name: {stack_name}")
    print(f"Region: {region}")
    print()
    
    # Initialize AWS clients
    try:
        cf_client = boto3.client('cloudformation', region_name=region)
        rds_client = boto3.client('rds', region_name=region)
    except Exception as e:
        print_color(f"Error initializing AWS clients: {e}", Colors.RED)
        sys.exit(1)
    
    # Check if stack exists
    if not check_stack_exists(cf_client, stack_name):
        print_color(f"Stack '{stack_name}' not found in region '{region}'", Colors.RED)
        sys.exit(1)
    
    print_color("Stack found. Beginning teardown process...", Colors.GREEN)
    print()
    
    # Step 1: Disable RDS deletion protection
    print_color("Step 1: Disabling RDS deletion protection...", Colors.YELLOW)
    rds_instances = get_stack_resources(cf_client, stack_name, 'AWS::RDS::DBInstance')
    
    if rds_instances:
        for db_instance_id in rds_instances:
            disable_rds_deletion_protection(rds_client, db_instance_id)
    else:
        print("No RDS instance found")
    print()
    
    # Step 2: Check CloudWatch log groups
    print_color("Step 2: Checking CloudWatch Log Groups...", Colors.YELLOW)
    log_groups = get_stack_resources(cf_client, stack_name, 'AWS::Logs::LogGroup')
    
    if log_groups:
        print(f"Found log groups: {', '.join(log_groups)}")
        print_color("Log groups will be deleted with stack", Colors.GREEN)
    else:
        print("No log groups found")
    print()
    
    # Step 3: Confirm and delete stack
    print_color("Step 3: Deleting CloudFormation stack...", Colors.YELLOW)
    print_color("WARNING: This will delete all resources including:", Colors.RED)
    print("  - RDS Database (a final snapshot will be created)")
    print("  - Lambda Functions")
    print("  - API Gateway")
    print("  - Secrets Manager secrets")
    print("  - Security Groups")
    print("  - VPC Endpoints")
    print("  - IAM Roles")
    print()
    
    confirm = input("Are you sure you want to continue? (yes/no): ")
    if confirm.lower() != 'yes':
        print_color("Teardown cancelled", Colors.YELLOW)
        sys.exit(0)
    
    if not delete_stack(cf_client, stack_name):
        sys.exit(1)
    print()
    
    # Step 4: Clean up orphaned resources
    print_color("Step 4: Checking for orphaned resources...", Colors.YELLOW)
    
    if rds_instances:
        cleanup_snapshots(rds_client, rds_instances[0], region)
    print()
    
    # Final summary
    print_color("=" * 40, Colors.GREEN)
    print_color("Teardown Complete!", Colors.GREEN)
    print_color("=" * 40, Colors.GREEN)
    print()
    print("Summary:")
    print("  ✓ Stack deleted")
    print("  ✓ RDS database deleted (snapshot created)")
    print("  ✓ All Lambda functions removed")
    print("  ✓ API Gateway deleted")
    print("  ✓ VPC endpoints removed")
    print("  ✓ Security groups deleted")
    print()
    print_color("Remember:", Colors.YELLOW)
    print("  - DB snapshots may still incur storage costs")
    print("  - Secrets are in recovery period (can be restored)")
    print("  - CloudWatch logs are deleted")
    print()

if __name__ == '__main__':
    main()
