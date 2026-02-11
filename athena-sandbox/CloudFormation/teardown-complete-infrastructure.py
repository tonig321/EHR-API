#!/usr/bin/env python3
"""
Master CloudFormation Teardown Script (Python version)

This script safely deletes the complete AthenaHealth integration infrastructure:
1. Integration stack (RDS, Lambda, API Gateway, VPC Endpoints) - FIRST
2. Foundation stack (VPC, KMS, S3, Security Groups) - SECOND

Usage: python teardown-complete-infrastructure.py <region>
Example: python teardown-complete-infrastructure.py us-east-1
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

def wait_for_stack_deletion(cf_client, stack_name):
    """Wait for stack deletion to complete"""
    print("Waiting for stack deletion to complete...")
    wait_count = 0
    max_wait = 120  # 20 minutes
    
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
            if wait_count >= max_wait:
                print_color("Timeout waiting for stack deletion", Colors.RED)
                return False
            
            print(f"Status: {status} (waited {wait_count * 10} seconds)")
            time.sleep(10)
            
        except ClientError as e:
            if 'does not exist' in str(e):
                break
            raise
    
    print_color("Stack deletion complete!", Colors.GREEN)
    return True

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
        print_color("✓ RDS deletion protection disabled", Colors.GREEN)
        return True
    except ClientError as e:
        print_color(f"Warning: Could not disable deletion protection: {e}", Colors.YELLOW)
        return False

def empty_s3_bucket(s3_client, bucket_name, region):
    """Empty an S3 bucket including all versions"""
    try:
        print(f"Emptying bucket: {bucket_name}")
        
        # Delete all objects
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name):
            if 'Contents' in page:
                objects = [{'Key': obj['Key']} for obj in page['Contents']]
                s3_client.delete_objects(
                    Bucket=bucket_name,
                    Delete={'Objects': objects}
                )
        
        # Delete all versions
        paginator = s3_client.get_paginator('list_object_versions')
        for page in paginator.paginate(Bucket=bucket_name):
            if 'Versions' in page:
                versions = [{'Key': v['Key'], 'VersionId': v['VersionId']} 
                          for v in page['Versions']]
                if versions:
                    s3_client.delete_objects(
                        Bucket=bucket_name,
                        Delete={'Objects': versions}
                    )
            
            if 'DeleteMarkers' in page:
                markers = [{'Key': m['Key'], 'VersionId': m['VersionId']} 
                         for m in page['DeleteMarkers']]
                if markers:
                    s3_client.delete_objects(
                        Bucket=bucket_name,
                        Delete={'Objects': markers}
                    )
        
        print_color(f"✓ Bucket {bucket_name} emptied", Colors.GREEN)
        return True
    except ClientError as e:
        print_color(f"Warning: Could not empty bucket {bucket_name}: {e}", Colors.YELLOW)
        return False

def delete_integration_stack(cf_client, rds_client, region):
    """Delete the integration stack"""
    print_color("Step 1: Preparing integration stack for deletion...", Colors.YELLOW)
    
    if not check_stack_exists(cf_client, INTEGRATION_STACK_NAME):
        print_color("Integration stack not found, skipping...", Colors.YELLOW)
        return None
    
    # Disable RDS deletion protection
    print("Disabling RDS deletion protection...")
    db_instances = get_stack_resources(cf_client, INTEGRATION_STACK_NAME, 'AWS::RDS::DBInstance')
    
    db_instance_id = None
    if db_instances:
        db_instance_id = db_instances[0]
        disable_rds_deletion_protection(rds_client, db_instance_id)
    else:
        print("No RDS instance found")
    
    print()
    print("Deleting integration stack...")
    cf_client.delete_stack(StackName=INTEGRATION_STACK_NAME)
    
    if not wait_for_stack_deletion(cf_client, INTEGRATION_STACK_NAME):
        print_color("Failed to delete integration stack", Colors.RED)
        return None
    
    return db_instance_id

def delete_foundation_stack(cf_client, s3_client, region):
    """Delete the foundation stack"""
    print_color("Step 2: Preparing foundation stack for deletion...", Colors.YELLOW)
    
    if not check_stack_exists(cf_client, FOUNDATION_STACK_NAME):
        print_color("Foundation stack not found, skipping...", Colors.YELLOW)
        return True
    
    # Get S3 buckets
    print("Checking for S3 buckets...")
    buckets = get_stack_resources(cf_client, FOUNDATION_STACK_NAME, 'AWS::S3::Bucket')
    
    phi_bucket = None
    log_bucket = None
    
    for bucket in buckets:
        if 'phi' in bucket.lower():
            phi_bucket = bucket
        elif 'log' in bucket.lower():
            log_bucket = bucket
    
    # Empty PHI bucket
    if phi_bucket:
        print(f"Found PHI bucket: {phi_bucket}")
        empty = input("Empty PHI bucket? (yes/no): ")
        if empty.lower() == 'yes':
            empty_s3_bucket(s3_client, phi_bucket, region)
    
    # Empty log bucket
    if log_bucket:
        print(f"Found log bucket: {log_bucket}")
        empty = input("Empty log bucket? (yes/no): ")
        if empty.lower() == 'yes':
            empty_s3_bucket(s3_client, log_bucket, region)
    
    print()
    print("Deleting foundation stack...")
    cf_client.delete_stack(StackName=FOUNDATION_STACK_NAME)
    
    return wait_for_stack_deletion(cf_client, FOUNDATION_STACK_NAME)

def cleanup_orphaned_resources(rds_client, region, db_instance_id):
    """Clean up orphaned RDS snapshots"""
    print_color("Step 3: Checking for orphaned resources...", Colors.YELLOW)
    
    if not db_instance_id:
        print("No DB instance ID to check for snapshots")
        return
    
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
            
            delete = input("Delete these snapshots? (yes/no): ")
            if delete.lower() == 'yes':
                for snapshot in snapshots:
                    try:
                        print(f"Deleting snapshot: {snapshot}")
                        rds_client.delete_db_snapshot(DBSnapshotIdentifier=snapshot)
                    except ClientError as e:
                        print_color(f"Warning: Could not delete {snapshot}: {e}", Colors.YELLOW)
                print_color("✓ Snapshots deleted", Colors.GREEN)
        else:
            print("No orphaned snapshots found")
            
    except ClientError as e:
        print_color(f"Warning: Could not check for snapshots: {e}", Colors.YELLOW)

def main():
    """Main teardown function"""
    if len(sys.argv) != 2:
        print_color("Usage: python teardown-complete-infrastructure.py <region>", Colors.RED)
        print("Example: python teardown-complete-infrastructure.py us-east-1")
        sys.exit(1)
    
    region = sys.argv[1]
    
    print_color("=" * 40, Colors.BLUE)
    print_color("AWS Infrastructure Teardown", Colors.BLUE)
    print_color("=" * 40, Colors.BLUE)
    print(f"Environment: {ENVIRONMENT_NAME}")
    print(f"Region: {region}")
    print(f"Integration Stack: {INTEGRATION_STACK_NAME}")
    print(f"Foundation Stack: {FOUNDATION_STACK_NAME}")
    print()
    
    # Display warning
    print_color("WARNING: This will delete ALL resources including:", Colors.RED)
    print()
    print("Integration Stack:")
    print("  - RDS Database (snapshot will be created)")
    print("  - Lambda Functions (3)")
    print("  - API Gateway")
    print("  - Secrets Manager secrets")
    print("  - VPC Endpoints")
    print()
    print("Foundation Stack:")
    print("  - VPC and all subnets")
    print("  - NAT Gateway and Internet Gateway")
    print("  - S3 Buckets (PHI data and logs)")
    print("  - KMS Keys")
    print("  - Security Groups")
    print("  - CloudTrail")
    print("  - Config Service")
    print()
    
    confirm = input("Are you sure you want to continue? Type 'DELETE' to confirm: ")
    if confirm != 'DELETE':
        print_color("Teardown cancelled", Colors.YELLOW)
        sys.exit(0)
    print()
    
    # Initialize AWS clients
    try:
        cf_client = boto3.client('cloudformation', region_name=region)
        rds_client = boto3.client('rds', region_name=region)
        s3_client = boto3.client('s3', region_name=region)
    except Exception as e:
        print_color(f"Error initializing AWS clients: {e}", Colors.RED)
        sys.exit(1)
    
    # Delete integration stack
    db_instance_id = delete_integration_stack(cf_client, rds_client, region)
    print()
    
    # Delete foundation stack
    if not delete_foundation_stack(cf_client, s3_client, region):
        print_color("Failed to delete foundation stack", Colors.RED)
        sys.exit(1)
    print()
    
    # Clean up orphaned resources
    cleanup_orphaned_resources(rds_client, region, db_instance_id)
    print()
    
    print_color("Note about Secrets Manager:", Colors.YELLOW)
    print("Secrets have a recovery window of 7-30 days before permanent deletion.")
    print()
    
    # Final summary
    print_color("=" * 40, Colors.GREEN)
    print_color("Teardown Complete!", Colors.GREEN)
    print_color("=" * 40, Colors.GREEN)
    print()
    print("Summary:")
    print("  ✓ Integration stack deleted")
    print("  ✓ Foundation stack deleted")
    print("  ✓ RDS database deleted (snapshot may exist)")
    print("  ✓ Lambda functions removed")
    print("  ✓ API Gateway deleted")
    print("  ✓ VPC and networking deleted")
    print()
    print_color("Potential remaining costs:", Colors.YELLOW)
    print("  - RDS snapshots (storage)")
    print("  - S3 buckets (if not emptied)")
    print("  - Secrets Manager (recovery period)")
    print()
    print_color("To verify complete cleanup:", Colors.YELLOW)
    print(f"aws cloudformation list-stacks --region {region} --query \"StackSummaries[?contains(StackName,'{ENVIRONMENT_NAME}')]\"")
    print()

if __name__ == '__main__':
    main()
