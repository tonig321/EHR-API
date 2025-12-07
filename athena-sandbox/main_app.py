# main_app.py  — run this on your laptop or any server
#anyone who runs main_app.py and whose AWS account (or IAM user/role) has permission to invoke the specified
# Lambda Function URL (or API Gateway) will be able to get a valid Athena access token and pull data from whatever 
# practice your client_id/secret is registered for.

import boto3  #the official AWS SDK for Python.Signs the HTTP request to your 
             #Lambda with your AWS credentials so IAM authentication works (SigV4Auth)
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import get_session

# ------------------------------------------------------------------
# 1. YOUR VALUES — change these two lines only
# ------------------------------------------------------------------
#TOKEN_URL = "https://{api-id}.execute-api.{region}.amazonaws.com/{stage}/{resource-path}" # Per Aamzon Q
TOKEN_URL = "https://9ulb7khdf3.execute-api.us-east-1.amazonaws.com/default/athena-token-server"
 #per Amazon Q
#TOKEN_URL = "https://9ulb7khdf3.execute-api.us-east-1.amazonaws.com/default"
#TOKEN_URL = "https://9ulb7khdf3.execute-api.us-east-1.amazonaws.com/default"
#TOKEN_URL = "https://9ulb7khdf3.execute-api.us-east-1.amazonaws.com/default/athena-token-server"   # ← the URL shown on the Lambda trigger line 
                 #plus, per grok, the stage name because When you added the API Gateway trigger from Lambda, AWS created an HTTP API, 
                 # not a REST API. HTTP APIs require a stage name in the URL — even if you never created one manually.




AWS_REGION = "us-east-1"                                               # ← same region as your Lambda

# ------------------------------------------------------------------
# 2. Helper — signs the request with IAM (no secrets in code)
# ------------------------------------------------------------------
def signed_get(url):
    session = boto3.Session()                     # uses your local AWS credentials (aws configure)
    credentials = session.get_credentials()
    request = AWSRequest(method="GET", url=url, headers={"Accept": "application/json"})
    SigV4Auth(credentials, "execute-api", AWS_REGION).add_auth(request)
    prep = request.prepare()
    return requests.get(prep.url, headers=dict(prep.headers))

# ------------------------------------------------------------------
# 3. Get fresh token from your Lambda
# ------------------------------------------------------------------
def get_token():
    r = signed_get(TOKEN_URL)
    r.raise_for_status()
    return r.json()["access_token"]

# ------------------------------------------------------------------
# 4. Real calls to AthenaHealth preview sandbox
# ------------------------------------------------------------------
def search_patients(name="smith"):
    url = "https://api.preview.platform.athenahealth.com/fhir/r4/Patient"
    headers = {"Authorization": f"Bearer {get_token()}"}
    params = {"name": name, "ah-practice": "Organization/a-1.Practice-195900"}
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()

def get_patient_appointments(patient_id):          # patient_id = the number like 10002
    url = f"https://api.preview.platform.athenahealth.com/v1/195900/patients/{patient_id}/appointments"
    r = requests.get(url, headers={"Authorization": f"Bearer {get_token()}"})
    r.raise_for_status()
    return r.json()

# ------------------------------------------------------------------
# 5. Run it
# ------------------------------------------------------------------
if __name__ == "__main__":
    patients = search_patients("smith")
    print(f"Found {patients['total']} Smith patients")

    first_id = patients["entry"][0]["resource"]["id"].split(".")[-1]
    print(f"Checking patient {first_id}")
    print("Appointments:", get_patient_appointments(first_id))