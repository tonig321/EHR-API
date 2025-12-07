# create_patient.py
# Works with your current Unified API / new portal app (2025)
# code created by Grok 11/29/25 based on my requirements
#WARNING - CREDENTIALS ARE HARDCODED FOR DEMO PURPOSES ONLY

import webbrowser
import urllib.parse
import requests
import json
import http.server
import socketserver
import threading
import time

# === YOUR CREDENTIALS (from .env or paste directly) ===
CLIENT_ID = "0oa101ockoysCPRLn298"          # ← your real client ID
CLIENT_SECRET = "FR3xTe148RZcjSREkBc0uCyw_6M5DPxu9NB6VGFZTsYX1L37WyskUP-XSbHcWZhq"   # ← paste your real secret here
REDIRECT_URI = "http://localhost:8080/callback"

# OAuth endpoints (preview sandbox)
AUTH_URL = "https://api.preview.platform.athenahealth.com/oauth2/v1/authorize"
TOKEN_URL = "https://api.preview.platform.athenahealth.com/oauth2/v1/token"
FHIR_URL = "https://api.preview.platform.athenahealth.com/fhir/r4/Patient"

# Scopes you said you have (V2 read/write)
SCOPE = "fhir/Patient.* openid fhirUser"

# --- Local server to catch the redirect ---
class Handler(http.server.SimpleHTTPRequestHandler):
    code = None
    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        if 'code' in params:
            self.server.code = params['code'][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Success! You can close this tab and return to terminal.</h1>")
        else:
            self.send_response(400)
            self.end_headers()

def start_server():
    with socketserver.TCPServer(("localhost", 8080), Handler) as httpd:
        httpd.code = None
        while httpd.code is None:
            httpd.handle_request()

print("Starting local server on http://localhost:8080 ...")
threading.Thread(target=start_server, daemon=True).start()

# --- Step 1: Open browser for login ---
auth_params = {
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPE,
    "state": "xyz123"
}
auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
print(f"Opening browser for login...\n   {auth_url}\n")
webbrowser.open(auth_url)

# --- Wait for authorization code ---
print("Waiting for you to log in and approve access...")
for _ in range(60):
    if hasattr(Handler, 'code') and Handler.code:
        auth_code = Handler.code
        break
    time.sleep(1)
else:
    print("Timeout — did you complete the login?")
    exit()

print(f"Got authorization code!")

# --- Step 2: Exchange code for token ---
token_resp = requests.post(TOKEN_URL, data={
    "grant_type": "authorization_code",
    "code": auth_code,
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET
})
token_resp.raise_for_status()
token = token_resp.json()["access_token"]
print(f"Got user token! (expires in {token_resp.json().get('expires_in', 3600)} seconds)")

# --- Step 3: Create Patient ---
patient_data = {
    "resourceType": "Patient",
    "name": [{"family": "Smith", "given": ["John"]}],
    "gender": "male",
    "birthDate": "1980-01-01",
    "telecom": [{"system": "phone", "value": "555-123-4567", "use": "home"}]
}

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}

print("Creating patient...")
r = requests.post(FHIR_URL, json=patient_data, headers=headers)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2))

if r.status_code == 201:
    patient_id = r.json()["id"]
    print(f"\nSUCCESS! Patient created with ID: {patient_id}")
else:
    print("\nFailed — but you now have a working user token for future calls")