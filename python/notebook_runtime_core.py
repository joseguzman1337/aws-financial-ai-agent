"""Core runtime logic for invocation notebook, callable from R via reticulate."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
import uuid
from typing import Any

import boto3
import requests
from botocore import UNSIGNED
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.credentials import Credentials


class NotebookRuntimeCore:
    def __init__(self, cfg: dict[str, Any] | None = None, params: dict[str, str] | None = None):
        self.cfg = {
            "region": "us-east-1",
            "agent_arn": "arn:aws:bedrock-agentcore:us-east-1:162187491349:runtime/Financial_Analyst_Agent-hvRgckAqaW",
            "identity_pool_id": "us-east-1:c7680c24-fe96-4358-b305-6f43de1ca6c8",
            "unauth_role_arn": "arn:aws:iam::162187491349:role/cognito_unauthenticated_role",
            "credential_refresh_seconds": 45 * 60,
            "model_id": "us.anthropic.claude-opus-4-6-v1",
            **(cfg or {}),
        }
        self.params = {
            "langfuse_pk": "/financial-ai/langfuse/public-key",
            "langfuse_sk": "/financial-ai/langfuse/secret-key",
            "langfuse_base_url": "/financial-ai/langfuse/base-url",
            **(params or {}),
        }
        self.session_id = str(uuid.uuid4())
        self.last_refresh = 0
        self.model_logged = False
        self.runtime_logged = False
        self.credentials: dict[str, str] | None = None
        self.refresh_clients()

    @property
    def agentcore_url(self) -> str:
        encoded = urllib.parse.quote(self.cfg["agent_arn"], safe="")
        return f"https://bedrock-agentcore.{self.cfg['region']}.amazonaws.com/runtimes/{encoded}/invocations"

    def refresh_clients(self) -> None:
        kw = {"region_name": self.cfg["region"]}
        if self.credentials:
            kw.update(
                aws_access_key_id=self.credentials["AccessKeyId"],
                aws_secret_access_key=self.credentials["SecretAccessKey"],
                aws_session_token=self.credentials["SessionToken"],
            )
        self.sts = boto3.client("sts", **kw)
        self.ssm = boto3.client("ssm", **kw)

    def bootstrap_guest(self) -> None:
        idc = boto3.client(
            "cognito-identity",
            region_name=self.cfg["region"],
            config=Config(signature_version=UNSIGNED),
        )
        identity_id = idc.get_id(IdentityPoolId=self.cfg["identity_pool_id"])["IdentityId"]
        token = idc.get_open_id_token(IdentityId=identity_id)["Token"]
        creds = boto3.client("sts", region_name=self.cfg["region"]).assume_role_with_web_identity(
            RoleArn=self.cfg["unauth_role_arn"],
            RoleSessionName="NotebookGuestSession",
            WebIdentityToken=token,
        )["Credentials"]
        self.credentials = {
            "AccessKeyId": creds["AccessKeyId"],
            "SecretAccessKey": creds["SecretAccessKey"],
            "SessionToken": creds["SessionToken"],
        }
        self.refresh_clients()
        self.last_refresh = int(time.time())

    def ensure_fresh(self, force: bool = False) -> None:
        age = int(time.time()) - int(self.last_refresh or 0)
        if force or self.last_refresh == 0 or age >= int(self.cfg["credential_refresh_seconds"]):
            self.bootstrap_guest()
            return
        try:
            self.sts.get_caller_identity()
        except Exception:
            self.bootstrap_guest()

    def ssm_get(self, name: str) -> str:
        try:
            return self.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
        except Exception as e:
            if "ExpiredToken" in str(e):
                self.bootstrap_guest()
                return self.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
            raise

    def _runtime_id(self) -> str:
        return self.cfg["agent_arn"].split("/")[-1]

    def print_runtime_info_once(self) -> None:
        if self.runtime_logged:
            return
        rid = self._runtime_id()
        try:
            env = os.environ.copy()
            if self.credentials:
                env["AWS_ACCESS_KEY_ID"] = self.credentials["AccessKeyId"]
                env["AWS_SECRET_ACCESS_KEY"] = self.credentials["SecretAccessKey"]
                env["AWS_SESSION_TOKEN"] = self.credentials["SessionToken"]
                env["AWS_REGION"] = self.cfg["region"]
            out = subprocess.check_output(
                [
                    "aws",
                    "bedrock-agentcore-control",
                    "get-agent-runtime",
                    "--region",
                    self.cfg["region"],
                    "--agent-runtime-id",
                    rid,
                    "--output",
                    "json",
                ],
                text=True,
                env=env,
            )
            js = json.loads(out)
            version = js.get("agentRuntimeVersion", "unknown")
            container = (
                js.get("agentRuntimeArtifact", {})
                .get("containerConfiguration", {})
                .get("containerUri", "unknown")
            )
            print(
                f"Runtime: id={rid} version={version} container={container} model={self.cfg['model_id']}"
            )
        except Exception:
            print(f"Runtime: id={rid} model={self.cfg['model_id']} (runtime metadata not available)")
        self.runtime_logged = True
        self.model_logged = True

    @staticmethod
    def _wrap(text: str, width: int = 79) -> str:
        import textwrap

        clean = " ".join((text or "").split())
        if not clean:
            return ""
        return "\n".join(textwrap.wrap(clean, width=width))

    @staticmethod
    def _event_text(ev: Any) -> str:
        if ev is None:
            return ""
        if isinstance(ev, str):
            return ev
        if isinstance(ev, list):
            return "".join(NotebookRuntimeCore._event_text(x) for x in ev)
        if isinstance(ev, dict):
            if "text" in ev:
                return str(ev["text"])
            if "content" in ev:
                return NotebookRuntimeCore._event_text(ev["content"])
        return str(ev)

    def query_agent(self, prompt: str) -> None:
        self.ensure_fresh()
        self.print_runtime_info_once()
        payload = json.dumps({"prompt": prompt}).encode("utf-8")
        req = AWSRequest(
            method="POST",
            url=self.agentcore_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": self.session_id,
            },
        )
        creds = Credentials(
            access_key=self.credentials["AccessKeyId"],
            secret_key=self.credentials["SecretAccessKey"],
            token=self.credentials["SessionToken"],
        )
        SigV4Auth(creds, "bedrock-agentcore", self.cfg["region"]).add_auth(req)
        headers = dict(req.prepare().headers)

        print(f"\nQ: {self._wrap(prompt)}")
        resp = requests.post(self.agentcore_url, headers=headers, data=payload, timeout=120, stream=True)
        print(
            "AgentCore metadata: runtimeSessionId={} statusCode={} contentType={}".format(
                self.session_id,
                resp.status_code,
                resp.headers.get("Content-Type", "unknown"),
            )
        )

        model_info = None
        token_usage: dict[str, int | None] = {"input": None, "output": None, "total": None}
        for k, v in resp.headers.items():
            lk = k.lower()
            if model_info is None and any(x in lk for x in ("model", "inference", "profile")) and v:
                model_info = f"{k}: {v}"

        parts: list[str] = []
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            s = line[5:].strip()
            try:
                evt = json.loads(s)
            except Exception:
                continue
            if "error" in evt:
                parts.append(f"Error: {evt['error']}")
                continue
            for mk in (
                "model",
                "modelId",
                "model_id",
                "inferenceProfileId",
                "inference_profile_id",
                "foundationModel",
            ):
                if model_info is None and evt.get(mk):
                    model_info = f"{mk}: {evt[mk]}"
            usage = evt.get("usage") or evt.get("tokenUsage") or {}
            if evt.get("inputTokens") is not None:
                token_usage["input"] = int(evt["inputTokens"])
            if evt.get("outputTokens") is not None:
                token_usage["output"] = int(evt["outputTokens"])
            if evt.get("totalTokens") is not None:
                token_usage["total"] = int(evt["totalTokens"])
            if usage:
                if usage.get("inputTokens") is not None:
                    token_usage["input"] = int(usage["inputTokens"])
                if usage.get("outputTokens") is not None:
                    token_usage["output"] = int(usage["outputTokens"])
                if usage.get("totalTokens") is not None:
                    token_usage["total"] = int(usage["totalTokens"])
                if usage.get("promptTokens") is not None:
                    token_usage["input"] = int(usage["promptTokens"])
                if usage.get("completionTokens") is not None:
                    token_usage["output"] = int(usage["completionTokens"])
            if "event" in evt:
                parts.append(self._event_text(evt["event"]))

        answer = self._wrap(" ".join(p for p in parts if p))
        print(f"A: {answer}")
        if token_usage["total"] is None and token_usage["input"] is not None and token_usage["output"] is not None:
            token_usage["total"] = int(token_usage["input"]) + int(token_usage["output"])
        if any(v is not None for v in token_usage.values()):
            print(
                "Tokens: input={} output={} total={}".format(
                    token_usage["input"] if token_usage["input"] is not None else "n/a",
                    token_usage["output"] if token_usage["output"] is not None else "n/a",
                    token_usage["total"] if token_usage["total"] is not None else "n/a",
                )
            )
        else:
            # AgentCore stream currently omits usage; fallback to Bedrock CountTokens.
            est_in, err_in = self._count_tokens_text(prompt, role="user")
            est_out, err_out = self._count_tokens_text(answer, role="assistant") if answer else (None, None)
            if est_in is not None or est_out is not None:
                est_total = (est_in or 0) + (est_out or 0)
                print(
                    "Tokens: input={} output={} total={} (source=bedrock:CountTokens estimate)".format(
                        est_in if est_in is not None else "n/a",
                        est_out if est_out is not None else "n/a",
                        est_total if (est_in is not None or est_out is not None) else "n/a",
                    )
                )
            else:
                reason = err_in or err_out or "unknown error"
                print(f"Tokens: not exposed by AgentCore metadata; CountTokens unavailable ({reason})")
        if (not self.model_logged) and model_info:
            print(f"Model: {model_info}")
            self.model_logged = True

    def _count_tokens_text(self, text: str, role: str) -> tuple[int | None, str | None]:
        try:
            req = {
                "converse": {
                    "messages": [
                        {"role": role, "content": [{"text": text or ""}]},
                    ]
                }
            }
            env = os.environ.copy()
            if self.credentials:
                env["AWS_ACCESS_KEY_ID"] = self.credentials["AccessKeyId"]
                env["AWS_SECRET_ACCESS_KEY"] = self.credentials["SecretAccessKey"]
                env["AWS_SESSION_TOKEN"] = self.credentials["SessionToken"]
            env["AWS_REGION"] = self.cfg["region"]
            proc = subprocess.run(
                [
                    "aws",
                    "bedrock-runtime",
                    "count-tokens",
                    "--region",
                    self.cfg["region"],
                    "--model-id",
                    self.cfg["model_id"],
                    "--input",
                    json.dumps(req, separators=(",", ":")),
                    "--output",
                    "json",
                ],
                text=True,
                env=env,
                capture_output=True,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                return None, err.splitlines()[-1] if err else "CountTokens command failed"
            resp = json.loads(proc.stdout)
            if "inputTokens" in resp and resp["inputTokens"] is not None:
                return int(resp["inputTokens"]), None
        except Exception as e:
            return None, str(e)
        return None, "empty CountTokens response"

    def verify_observability(self) -> None:
        self.ensure_fresh()
        pk = self.ssm_get(self.params["langfuse_pk"])
        sk = self.ssm_get(self.params["langfuse_sk"])
        base = self.ssm_get(self.params["langfuse_base_url"]).rstrip("/")
        arn = self.sts.get_caller_identity()["Arn"]
        print(f"Observability identity: {arn}")
        print(f"Success: retrieved Langfuse keys (PK: {pk[:7]}...)")
        auth = requests.get(f"{base}/api/public/projects", auth=(pk, sk), timeout=30)
        print(f"Langfuse auth status: {auth.status_code}")
