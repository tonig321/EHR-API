#Second take after much time was spent determining Lambdba deployment package issues with requests library specifically,
# and apparently all external dependencies are a no-go for this environment.
#  
# =============================================================================
# AthenaHealth Token Server (Lambda) — 100% built-in libraries, no dependencies
# Purpose: Securely fetch and cache an OAuth2 access token from AthenaHealth
#          using client_credentials (2-legged) flow in the preview sandbox.
# =============================================================================

import json                 # Built-in: parse JSON strings ↔ Python dicts
import urllib.parse         # Built-in: safely encode URL parameters
import urllib.request       # Built-in: make HTTP POST requests (like curl)
import boto3                # AWS SDK (pre-installed in Lambda) — talks to Secrets Manager
import time                 # Built-in: track token expiry time

# -----------------------------------------------------------------------------
# Global variables — these survive between Lambda invocations when the container
# is reused (free in-memory caching = big performance win)
# -----------------------------------------------------------------------------
_cached_token: str | None = None      # Holds the current access token
_cached_expiry: float = 0             # Unix timestamp when token expires

# -----------------------------------------------------------------------------
# Step 1: Pull your secret (client_id + client_secret) from AWS Secrets Manager
# -----------------------------------------------------------------------------
def get_secret() -> tuple[str, str]:
    """
    Retrieves your AthenaHealth client_id and client_secret from Secrets Manager.
    Returns a tuple: (client_id, client_secret)
    Looks in AWS Secrets Manager for a secret named athena-preview-creds and pulls the client_id and client_secret from it."

    """
    client = boto3.client('secretsmanager')                     # AWS service client
    response = client.get_secret_value(SecretId='athena-preview-creds')
    
    # The secret is stored as JSON string → convert to Python dict
    secret_dict = json.loads(response['SecretString'])
    
    return secret_dict['client_id'], secret_dict['client_secret']


# -----------------------------------------------------------------------------
# Step 2: Request a fresh token from AthenaHealth
# -----------------------------------------------------------------------------
def get_fresh_token() -> tuple[str, float]:
    """
    Calls AthenaHealth's token endpoint and returns:
        - access_token (string)
        - expiry_timestamp (float) — when the token dies (so we can refresh early)
    """
    client_id, client_secret = get_secret()

    # The URL for preview sandbox (production uses api.platform.athenahealth.com)
    token_url = "https://api.preview.platform.athenahealth.com/oauth2/v1/token"

    # Body data required by OAuth2 client_credentials flow
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "system/Patient.read system/Appointment.read system/Encounter.read"
    }

    # Convert dict → URL-encoded string → bytes (required for POST)
    encoded_data = urllib.parse.urlencode(data).encode('utf-8')

    # Build the HTTP request
    req = urllib.request.Request(
        url=token_url,
        data=encoded_data,
        method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    # Send request and read response
    with urllib.request.urlopen(req) as response:
        raw_body = response.read().decode('utf-8')      # bytes → string
        token_json = json.loads(raw_body)               # string → dict

    access_token = token_json["access_token"]
    expires_in = token_json["expires_in"]               # seconds until expiry

    # Return token + safe expiry time (refresh 60 seconds early)
    expiry_time = time.time() + expires_in - 60
    return access_token, expiry_time


# -----------------------------------------------------------------------------
# Step 3: Main Lambda handler — AWS calls this function on every invoke
# -----------------------------------------------------------------------------
def lambda_handler(event, context):
    """
    This is the entry point for Lambda.
    It returns a fresh or cached access token as JSON.
    """
    global _cached_token, _cached_expiry

    # If we don't have a token or it's about to expire → fetch new one
    if _cached_token is None or time.time() > _