"""
Automated verification script to execute required financial queries.
This script is triggered by Terraform to ensure Langfuse traces are captured.
"""

import os
import sys
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


def get_auth_token(client_id: str, region: str) -> str:
    """Authenticates and returns AccessToken."""
    user = "analyst_user"
    pw = os.environ.get("ANALYST_PASSWORD", "SecurePassword123!")
    client = boto3.client("cognito-idp", region_name=region)
    auth_resp = client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": user, "PASSWORD": pw},
    )
    return str(auth_resp["AuthenticationResult"]["AccessToken"])


def verify() -> None:
    """
    Invokes the Bedrock AgentCore runtime for required queries.
    """
    cfg = get_env_config()

    if not all([cfg["client_id"], cfg["agent_arn"], cfg["account_id"]]):
        print("❌ Missing required environment variables.")
        sys.exit(1)

    print("--- Starting Automated Verification ---")

    try:
        token = get_auth_token(cfg["client_id"], cfg["region"])
        print("✅ Authenticated successfully.")
    except Exception as error:
        print(f"❌ Auth Failed: {error}")
        sys.exit(1)

    enc_arn = urllib.parse.quote(cfg["agent_arn"], safe="")
    url = (
        f"https://bedrock-agentcore.{cfg['region']}.amazonaws.com"
        f"/runtimes/{enc_arn}/invocations"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": (
            "terraform-verify-session-recruiter-proof-2026"
        ),
    }

    queries = [
        "What is the stock price for Amazon right now?",
        "What were the stock prices for Amazon in Q4 last year?",
        "Compare Amazon's stock performance to what analysts predicted.",
        "Give me current AMZN price and info about their AI business.",
        "What is total amount of office space Amazon owned in NA in 2024?",
    ]

    for query in queries:
        print(f"\nQuerying: {query}")
        try:
            resp = requests.post(url, headers=headers, json={"prompt": query})
            if resp.status_code == 200:
                print("✅ Success (Trace captured in Langfuse)")
            else:
                print(f"⚠️ Error {resp.status_code}: {resp.text}")
        except Exception as error:
            print(f"❌ Request failed: {error}")

    print("\n--- Verification Complete ---")


if __name__ == "__main__":
    verify()
