"""Langfuse runtime configuration helpers with SSM fallback and masking."""

import os
import re
from typing import Any

import boto3
from langfuse import Langfuse


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


def _default_mask(data: Any, **_kwargs) -> Any:
    """Mask common PII/secrets before sending to Langfuse."""
    if isinstance(data, str):
        masked = data
        masked = re.sub(
            r"\b[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}\b",
            "[REDACTED_EMAIL]",
            masked,
        )
        masked = re.sub(
            r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b",
            "[REDACTED_PHONE]",
            masked,
        )
        masked = re.sub(
            r"\b(?:\d[ -]*?){13,19}\b",
            "[REDACTED_CARD]",
            masked,
        )
        return masked
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            lk = str(k).lower()
            if any(
                x in lk
                for x in (
                    "password",
                    "secret",
                    "token",
                    "api_key",
                    "apikey",
                    "authorization",
                )
            ):
                out[str(k)] = "[REDACTED_SECRET]"
            else:
                out[str(k)] = _default_mask(v)
        return out
    if isinstance(data, list):
        return [_default_mask(x) for x in data]
    return data


_CLIENT: Langfuse | None = None


def get_langfuse_client() -> Langfuse:
    """Get singleton Langfuse client with optional masking enabled."""
    global _CLIENT  # pylint: disable=global-statement
    if _CLIENT is not None:
        return _CLIENT
    if not ensure_langfuse_env():
        raise RuntimeError("Langfuse env not configured")
    base_url = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    use_mask = os.environ.get("LANGFUSE_ENABLE_MASKING", "1") == "1"
    kwargs = {
        "public_key": os.environ["LANGFUSE_PUBLIC_KEY"],
        "secret_key": os.environ["LANGFUSE_SECRET_KEY"],
        "host": base_url,
    }
    release = os.environ.get("LANGFUSE_RELEASE")
    if release:
        kwargs["release"] = release
    flush_at = os.environ.get("LANGFUSE_FLUSH_AT")
    flush_interval = os.environ.get("LANGFUSE_FLUSH_INTERVAL")
    if flush_at:
        try:
            kwargs["flush_at"] = int(flush_at)
        except ValueError:
            pass
    if flush_interval:
        try:
            kwargs["flush_interval"] = float(flush_interval)
        except ValueError:
            pass
    if use_mask:
        kwargs["mask"] = _default_mask
    _CLIENT = Langfuse(**kwargs)
    return _CLIENT
