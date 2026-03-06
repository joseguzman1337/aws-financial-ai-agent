"""Verify LangChain API keys stored in AWS SSM and test LangSmith auth."""

import os
import sys

import boto3
import requests


def _mask(value: str) -> str:
    if len(value) < 12:
        return "***"
    return f"{value[:8]}***{value[-6:]}"


def _get_ssm_value(name: str, region: str) -> str:
    ssm = boto3.client("ssm", region_name=region)
    resp = ssm.get_parameter(Name=name, WithDecryption=True)
    return str(resp["Parameter"]["Value"])


def _check_langsmith_api(key: str) -> int:
    resp = requests.get(
        "https://api.smith.langchain.com/info",
        headers={"x-api-key": key},
        timeout=20,
    )
    return resp.status_code


def main() -> int:
    region = os.environ.get("AWS_REGION", "us-east-1")
    names = {
        "personal": "/financial-ai/langchain/personal-key",
        "service": "/financial-ai/langchain/service-key",
    }

    print(f"Using region: {region}")
    ok = True

    for kind, param_name in names.items():
        try:
            key = _get_ssm_value(param_name, region)
            if "placeholder" in key.lower():
                print(f"❌ {kind}: placeholder value in {param_name}")
                ok = False
                continue

            status = _check_langsmith_api(key)
            if status == 200:
                print(f"✅ {kind}: {param_name} [{_mask(key)}] auth OK")
            else:
                print(
                    f"❌ {kind}: {param_name} [{_mask(key)}] auth failed "
                    f"(HTTP {status})"
                )
                ok = False
        except Exception as error:
            print(f"❌ {kind}: verification error for {param_name}: {error}")
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
