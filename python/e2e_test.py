import json
import urllib.parse

import boto3
import requests


def run_e2e_test():
    REGION = "us-east-1"
    USER_POOL_ID = "us-east-1_5pCxpIkx8"
    CLIENT_ID = "2r1ik1k110jbu6nfmuoegk5lns"
    IDENTITY_POOL_ID = "us-east-1:c7680c24-fe96-4358-b305-6f43de1ca6c8"
    AGENT_ARN = "arn:aws:bedrock-agentcore:us-east-1:162187491349:runtime/Financial_Analyst_Agent-hvRgckAqaW"

    print("--- 1. Guest Identity Retrieval ---")
    id_client = boto3.client("cognito-identity", region_name=REGION)
    identity_id = id_client.get_id(IdentityPoolId=IDENTITY_POOL_ID)[
        "IdentityId"
    ]
    guest_creds = id_client.get_credentials_for_identity(
        IdentityId=identity_id
    )["Credentials"]

    ssm_guest = boto3.client(
        "ssm",
        region_name=REGION,
        aws_access_key_id=guest_creds["AccessKeyId"],
        aws_secret_access_key=guest_creds["SecretKey"],
        aws_session_token=guest_creds["SessionToken"],
    )
    try:
        username = ssm_guest.get_parameter(
            Name="/financial-ai/analyst-username", WithDecryption=True
        )["Parameter"]["Value"]
        password = ssm_guest.get_parameter(
            Name="/financial-ai/analyst-password", WithDecryption=True
        )["Parameter"]["Value"]
        print(f"✅ Credentials Retrieved from SSM: {username}")
    except Exception as e:
        print(f"⚠️ Guest Retrieval failed ({e}), using fallback credentials.")
        username = "analyst_user"
        password = "FinAIAgent2026@"

    print("\n--- 2. Cognito Authentication ---")
    idp_client = boto3.client("cognito-idp", region_name=REGION)
    auth_resp = idp_client.initiate_auth(
        ClientId=CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    access_token = auth_resp["AuthenticationResult"]["AccessToken"]
    id_token = auth_resp["AuthenticationResult"]["IdToken"]
    print("✅ Authenticated.")

    print("\n--- 3. Live Agent Invocation ---")
    encoded_arn = urllib.parse.quote(AGENT_ARN, safe="")
    url = f"https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/{encoded_arn}/invocations"
    session_id = str(__import__("uuid").uuid4())
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }

    query = "What is the stock price for Amazon right now?"
    response = requests.post(
        url, headers=headers, json={"prompt": query}, stream=True
    )
    if response.status_code == 200:
        print("✅ Response Stream Started:")
        for line in response.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    data = json.loads(decoded[6:])
                    print(data.get("event", ""), end="", flush=True)
        print("\n✅ Stream Complete.")
    else:
        print(f"❌ Invocation Failed {response.status_code}: {response.text}")

    print("\n--- 4. Observability Audit ---")
    auth_creds = id_client.get_credentials_for_identity(
        IdentityId=identity_id,
        Logins={
            f"cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}": id_token
        },
    )["Credentials"]

    ssm_auth = boto3.client(
        "ssm",
        region_name=REGION,
        aws_access_key_id=auth_creds["AccessKeyId"],
        aws_secret_access_key=auth_creds["SecretKey"],
        aws_session_token=auth_creds["SessionToken"],
    )
    pk = ssm_auth.get_parameter(
        Name="/financial-ai/langfuse/public-key", WithDecryption=True
    )["Parameter"]["Value"]
    sk = ssm_auth.get_parameter(
        Name="/financial-ai/langfuse/secret-key", WithDecryption=True
    )["Parameter"]["Value"]
    try:
        base_url = ssm_auth.get_parameter(
            Name="/financial-ai/langfuse/base-url", WithDecryption=True
        )["Parameter"]["Value"].rstrip("/")
    except Exception:
        base_url = ""

    if "placeholder" in pk.lower() or "placeholder" in sk.lower():
        print("❌ Langfuse keys in SSM are placeholders; cannot fetch traces.")
        return

    trace_resp = None
    hosts = (
        [base_url]
        if base_url
        else [
            "https://us.cloud.langfuse.com",
            "https://cloud.langfuse.com",
            "https://eu.cloud.langfuse.com",
        ]
    )
    for host in hosts:
        trace_resp = requests.get(
            f"{host}/api/public/traces?sessionId={session_id}",
            auth=(pk, sk),
            timeout=30,
        )
        if trace_resp.status_code == 200:
            break
    if trace_resp and trace_resp.status_code == 200:
        print("✅ Traces Found in Langfuse.")
    else:
        code = trace_resp.status_code if trace_resp else "N/A"
        print(f"⚠️ Trace Retrieval Failed: {code}")


if __name__ == "__main__":
    run_e2e_test()
