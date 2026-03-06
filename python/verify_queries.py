"""
Automated verification script using direct HTTPS to Bedrock AgentCore.
Retrieves credentials from SSM and fetches traces from Langfuse as proof.
"""

import json
import os
import sys
import time
import urllib.parse
from typing import Dict

import boto3
import requests  # type: ignore


def get_env_config() -> Dict[str, str]:
    """Retrieves all required environment configuration."""
    return {
        "region": os.environ.get("AWS_REGION", "us-east-1"),
        "client_id": os.environ.get("COGNITO_CLIENT_ID", ""),
        "agent_arn": str(os.environ.get("AGENT_ARN", "")),
        "account_id": str(os.environ.get("ACCOUNT_ID", "")),
    }


def get_ssm_param(name: str, region: str) -> str:
    """Retrieves a secure parameter from SSM."""
    client = boto3.client("ssm", region_name=region)
    resp = client.get_parameter(Name=name, WithDecryption=True)
    return str(resp["Parameter"]["Value"])


def get_auth_token(client_id: str, region: str) -> str:
    """Authenticates and returns AccessToken."""
    user = "analyst_user"
    pw = os.environ.get("ANALYST_PASSWORD", "FinAIAgent2026@")
    client = boto3.client("cognito-idp", region_name=region)
    auth_resp = client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": user, "PASSWORD": pw},
    )
    return str(auth_resp["AuthenticationResult"]["AccessToken"])


def verify() -> None:
    """
    Invokes the Bedrock AgentCore runtime and verifies Langfuse traces.
    """
    cfg = get_env_config()

    if not all([cfg["client_id"], cfg["agent_arn"], cfg["account_id"]]):
        print("❌ Missing required environment variables.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("🚀 STARTING AUTOMATED AGENT VERIFICATION")
    print("=" * 60)

    try:
        token = get_auth_token(cfg["client_id"], cfg["region"])
        print("✅ Authenticated with Cognito.")
    except Exception as error:
        print(f"❌ Auth Failed: {error}")
        sys.exit(1)

    encoded_arn = urllib.parse.quote(cfg["agent_arn"], safe="")
    url = (
        f"https://bedrock-agentcore.{cfg['region']}.amazonaws.com"
        f"/runtimes/{encoded_arn}/invocations"
    )

    sid = os.environ.get("E2E_SESSION_ID", str(__import__("uuid").uuid4()))
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sid,
    }

    # Execute required queries
    queries = [
        "What is the stock price for Amazon right now?",
        "What is total amount of office space Amazon owned in NA in 2024?",
    ]

    for query in queries:
        print(f"\n📝 QUERY: {query}")
        try:
            resp = requests.post(url, headers=headers, json={"prompt": query})
            if resp.status_code == 200:
                print("✅ Agent Invocation Successful.")
            else:
                print(f"❌ Invocation Failed {resp.status_code}: {resp.text}")
        except Exception as error:
            print(f"❌ Request failed: {error}")

    # 4. Fetch Trace from Langfuse using Keys from SSM
    print("\n🔍 RETRIEVING OBSERVABILITY TRACES FROM LANGFUSE...")
    try:
        pk = get_ssm_param("/financial-ai/langfuse/public-key", cfg["region"])
        sk = get_ssm_param("/financial-ai/langfuse/secret-key", cfg["region"])

        # Wait for trace propagation
        time.sleep(5)

        if "placeholder" in pk.lower() or "placeholder" in sk.lower():
            print(
                "❌ Langfuse keys in SSM are placeholders; cannot fetch traces."
            )
            return

        trace_hosts = [
            "https://us.cloud.langfuse.com",
            "https://cloud.langfuse.com",
            "https://eu.cloud.langfuse.com",
        ]
        trace_resp = None
        for host in trace_hosts:
            trace_url = f"{host}/api/public/traces?sessionId={sid}"
            trace_resp = requests.get(trace_url, auth=(pk, sk), timeout=30)
            if trace_resp.status_code == 200:
                break

        if trace_resp and trace_resp.status_code == 200:
            traces = trace_resp.json().get("data", [])
            if traces:
                print("✅ Langfuse Traces Found:")
                print(json.dumps(traces[0], indent=2))
            else:
                print("⚠️ No traces found yet for this session.")
        else:
            code = trace_resp.status_code if trace_resp else "N/A"
            print(f"❌ Failed to fetch traces: {code}")
    except Exception as error:
        print(f"❌ Trace verification failed: {error}")

    print("\n" + "=" * 60)
    print("🎯 VERIFICATION COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    verify()
