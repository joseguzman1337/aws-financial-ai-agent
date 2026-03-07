"""Langfuse runtime configuration helpers with SSM fallback."""

import os

import boto3


def _get_ssm(name: str, region: str) -> str:
    client = boto3.client("ssm", region_name=region)
    return str(
        client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    )


def ensure_langfuse_env() -> bool:
    """
    Ensures Langfuse env vars are available.
    Priority: existing env vars, then SSM/KMS fallback.
    """
    required = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    if all(os.environ.get(name) for name in required):
        return True

    region = os.environ.get("AWS_REGION", "us-east-1")
    mapping = {
        "LANGFUSE_PUBLIC_KEY": "/financial-ai/langfuse/public-key",
        "LANGFUSE_SECRET_KEY": "/financial-ai/langfuse/secret-key",
        "LANGFUSE_BASE_URL": "/financial-ai/langfuse/base-url",
    }
    try:
        for env_name, ssm_name in mapping.items():
            if not os.environ.get(env_name):
                value = _get_ssm(ssm_name, region)
                if value and "placeholder" not in value.lower():
                    os.environ[env_name] = value
        return all(os.environ.get(name) for name in required)
    except Exception:
        return False
