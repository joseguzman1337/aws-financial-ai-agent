"""Reusable helpers for notebook-style SigV4 AgentCore invocation flow."""

from __future__ import annotations

import json
import os
import urllib.parse
import uuid
from typing import Any

import boto3
import requests
from botocore import UNSIGNED
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.session import Session


def build_agentcore_url(region: str, agent_arn: str) -> str:
    encoded = urllib.parse.quote(agent_arn, safe="")
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/"
        f"runtimes/{encoded}/invocations"
    )


def bootstrap_guest_credentials(
    region: str,
    identity_pool_id: str,
    unauth_role_arn: str,
) -> dict[str, str]:
    """Fetches guest AWS credentials for notebook flow."""
    idc = boto3.client(
        "cognito-identity",
        region_name=region,
        config=Config(signature_version=UNSIGNED),
    )
    identity_id = idc.get_id(IdentityPoolId=identity_pool_id)["IdentityId"]

    try:
        token = idc.get_open_id_token(IdentityId=identity_id)["Token"]
        creds = boto3.client("sts", region_name=region).assume_role_with_web_identity(
            RoleArn=unauth_role_arn,
            RoleSessionName="NotebookGuestSession",
            WebIdentityToken=token,
        )["Credentials"]
        access_key = str(creds["AccessKeyId"])
        secret_key = str(creds["SecretAccessKey"])
        session_token = str(creds["SessionToken"])
    except Exception:
        creds = idc.get_credentials_for_identity(IdentityId=identity_id)[
            "Credentials"
        ]
        access_key = str(creds["AccessKeyId"])
        secret_key = str(creds["SecretKey"])
        session_token = str(creds["SessionToken"])

    os.environ["AWS_ACCESS_KEY_ID"] = access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = secret_key
    os.environ["AWS_SESSION_TOKEN"] = session_token

    return {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "aws_session_token": session_token,
    }


def event_text(event: Any) -> str:
    """Parses event payload shapes returned by AgentCore SSE."""
    if isinstance(event, str):
        return event
    if isinstance(event, list):
        return "".join(
            part.get("text", "")
            for part in event
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if isinstance(event, dict):
        if "text" in event:
            return str(event["text"])
        if "content" in event:
            return event_text(event["content"])
    return str(event)


def invoke_query(
    region: str,
    agent_arn: str,
    prompt: str,
    session_id: str | None = None,
    timeout: int = 180,
) -> tuple[bool, str]:
    """Invokes AgentCore runtime with SigV4 and returns (ok, response)."""
    sid = session_id or str(uuid.uuid4())
    url = build_agentcore_url(region, agent_arn)
    payload = json.dumps({"prompt": prompt}).encode("utf-8")

    request = AWSRequest(
        method="POST",
        url=url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sid,
        },
    )
    creds = Session().get_credentials()
    if creds is None:
        return False, "No AWS credentials available for SigV4 signing."
    SigV4Auth(creds.get_frozen_credentials(), "bedrock-agentcore", region).add_auth(
        request
    )

    response = requests.post(
        url,
        headers=dict(request.prepare().headers),
        data=payload,
        stream=True,
        timeout=timeout,
    )
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: {response.text[:300]}"

    chunks = []
    for line in response.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8")
        if not decoded.startswith("data: "):
            continue
        data = json.loads(decoded[6:])
        if "error" in data:
            return False, f"event_error: {str(data['error'])[:300]}"
        if "event" in data:
            chunks.append(event_text(data["event"]))

    text = "".join(chunks).strip()
    if not text:
        return False, "empty_response"
    return True, text
