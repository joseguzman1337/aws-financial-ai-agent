"""Passwordless SigV4 E2E verification for Bedrock AgentCore runtime."""

import json
import os
import sys
import time
import urllib.parse
import uuid

import boto3
import requests  # type: ignore
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session


def get_env_config() -> dict[str, str]:
    return {
        "region": os.environ.get("AWS_REGION", "us-east-1"),
        "agent_arn": str(os.environ.get("AGENT_ARN", "")),
    }


def get_ssm_param(name: str, region: str) -> str:
    client = boto3.client("ssm", region_name=region)
    resp = client.get_parameter(Name=name, WithDecryption=True)
    return str(resp["Parameter"]["Value"])


def sigv4_headers(url: str, payload: bytes, region: str, sid: str) -> dict[str, str]:
    creds = Session().get_credentials()
    if creds is None:
        raise RuntimeError("No AWS credentials found for SigV4 signing.")

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sid,
    }
    request = AWSRequest(method="POST", url=url, data=payload, headers=headers)
    SigV4Auth(creds.get_frozen_credentials(), "bedrock-agentcore", region).add_auth(
        request
    )
    return dict(request.prepare().headers)


def verify() -> None:
    cfg = get_env_config()
    if not cfg["agent_arn"]:
        print("❌ Missing AGENT_ARN environment variable.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("🚀 STARTING PASSWORDLESS SIGV4 AGENT VERIFICATION")
    print("=" * 60)

    encoded_arn = urllib.parse.quote(cfg["agent_arn"], safe="")
    url = (
        f"https://bedrock-agentcore.{cfg['region']}.amazonaws.com"
        f"/runtimes/{encoded_arn}/invocations"
    )
    sid = os.environ.get("E2E_SESSION_ID", str(uuid.uuid4()))

    queries = [
        "What is the stock price for Amazon right now?",
        "What is total amount of office space Amazon owned in NA in 2024?",
    ]

    for query in queries:
        print(f"\n📝 QUERY: {query}")
        try:
            payload = json.dumps({"prompt": query}).encode("utf-8")
            headers = sigv4_headers(url, payload, cfg["region"], sid)
            resp = requests.post(url, headers=headers, data=payload, timeout=120)
            if resp.status_code == 200:
                print("✅ Agent Invocation Successful.")
            else:
                print(f"❌ Invocation Failed {resp.status_code}: {resp.text[:300]}")
        except Exception as error:
            print(f"❌ Request failed: {error}")

    print("\n🔍 RETRIEVING OBSERVABILITY TRACES FROM LANGFUSE...")
    try:
        pk = get_ssm_param("/financial-ai/langfuse/public-key", cfg["region"])
        sk = get_ssm_param("/financial-ai/langfuse/secret-key", cfg["region"])
        try:
            base_url = get_ssm_param(
                "/financial-ai/langfuse/base-url", cfg["region"]
            ).rstrip("/")
        except Exception:
            base_url = ""
        if "placeholder" in pk.lower() or "placeholder" in sk.lower():
            print("❌ Langfuse keys in SSM are placeholders; cannot fetch traces.")
            return

        time.sleep(5)
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
            trace_url = f"{host}/api/public/traces?sessionId={sid}"
            trace_resp = requests.get(trace_url, auth=(pk, sk), timeout=30)
            if trace_resp.status_code == 200:
                traces = trace_resp.json().get("data", [])
                if traces:
                    print("✅ Langfuse Traces Found.")
                else:
                    print("⚠️ No traces found yet for this session.")
                break
        else:
            print("❌ Failed to fetch traces from Langfuse hosts.")
    except Exception as error:
        print(f"❌ Trace verification failed: {error}")

    print("\n" + "=" * 60)
    print("🎯 VERIFICATION COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    verify()
