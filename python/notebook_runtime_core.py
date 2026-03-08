"""Core runtime logic for invocation notebook, callable from R via reticulate."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

import boto3
import requests
from botocore import UNSIGNED
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.credentials import Credentials


class NotebookRuntimeCore:
    RUNTIME_VERSION = "2026-03-08-observability-v3"

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ):
        self.cfg = {
            "region": "us-east-1",
            "agent_arn": "arn:aws:bedrock-agentcore:us-east-1:162187491349:runtime/Financial_Analyst_Agent-hvRgckAqaW",
            "identity_pool_id": "us-east-1:c7680c24-fe96-4358-b305-6f43de1ca6c8",
            "unauth_role_arn": "arn:aws:iam::162187491349:role/cognito_unauthenticated_role",
            "credential_refresh_seconds": 45 * 60,
            "model_id": "us.anthropic.claude-opus-4-6-v1",
            "invocation_log_group": "/aws/bedrock/model-invocations/Financial_Analyst_Agent",
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
        self.chat_css_loaded = False
        self.credentials: dict[str, str] | None = None
        self.refresh_clients()

    def _aws_cmd(self) -> list[str]:
        """Resolve AWS CLI invocation across mixed notebook runtimes."""
        aws_bin = shutil.which("aws")
        if aws_bin:
            return [aws_bin]
        try:
            import awscli  # type: ignore  # noqa: F401

            return [sys.executable, "-m", "awscli"]
        except Exception:
            pass
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "awscli"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return [sys.executable, "-m", "awscli"]
        except Exception:
            return ["aws"]

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
        self.logs = boto3.client("logs", **kw)

    def bootstrap_guest(self) -> None:
        idc = boto3.client(
            "cognito-identity",
            region_name=self.cfg["region"],
            config=Config(signature_version=UNSIGNED),
        )
        identity_id = idc.get_id(IdentityPoolId=self.cfg["identity_pool_id"])[
            "IdentityId"
        ]
        token = idc.get_open_id_token(IdentityId=identity_id)["Token"]
        creds = boto3.client(
            "sts", region_name=self.cfg["region"]
        ).assume_role_with_web_identity(
            RoleArn=self.cfg["unauth_role_arn"],
            RoleSessionName="NotebookGuestSession",
            WebIdentityToken=token,
        )[
            "Credentials"
        ]
        self.credentials = {
            "AccessKeyId": creds["AccessKeyId"],
            "SecretAccessKey": creds["SecretAccessKey"],
            "SessionToken": creds["SessionToken"],
        }
        self.refresh_clients()
        self.last_refresh = int(time.time())

    def ensure_fresh(self, force: bool = False) -> None:
        age = int(time.time()) - int(self.last_refresh or 0)
        if (
            force
            or self.last_refresh == 0
            or age >= int(self.cfg["credential_refresh_seconds"])
        ):
            self.bootstrap_guest()
            return
        try:
            self.sts.get_caller_identity()
        except Exception:
            self.bootstrap_guest()

    def ssm_get(self, name: str) -> str:
        try:
            return self.ssm.get_parameter(Name=name, WithDecryption=True)[
                "Parameter"
            ]["Value"]
        except Exception as e:
            if "ExpiredToken" in str(e):
                self.bootstrap_guest()
                return self.ssm.get_parameter(Name=name, WithDecryption=True)[
                    "Parameter"
                ]["Value"]
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
                env["AWS_SECRET_ACCESS_KEY"] = self.credentials[
                    "SecretAccessKey"
                ]
                env["AWS_SESSION_TOKEN"] = self.credentials["SessionToken"]
                env["AWS_REGION"] = self.cfg["region"]
            out = subprocess.check_output(
                self._aws_cmd()
                + [
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
            print(
                f"Runtime: id={rid} model={self.cfg['model_id']} (runtime metadata not available)"
            )
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

    def _render_chat_box(
        self,
        role: str,
        text: str,
        markdown_enabled: bool = False,
        display_id: str | None = None,
        update: bool = False,
    ) -> None:
        """Render Q/A boxes in notebooks with markdown support."""
        try:
            from IPython.display import HTML, display, update_display  # type: ignore
        except Exception:
            prefix = "Q" if role == "q" else "A"
            if not update:
                print(f"{prefix}: {self._wrap(text)}")
            return

        if not self.chat_css_loaded:
            css = """
<style>
.af-chat{display:flex;flex-direction:column;gap:.55rem;margin:.4rem 0 1rem 0;font-family:ui-sans-serif,system-ui}
.af-msg{max-width:79ch;border-radius:14px;padding:.7rem .85rem;line-height:1.4;box-shadow:0 1px 6px rgba(0,0,0,.28);overflow:auto;color:#f5f7fa}
.af-q{margin-right:auto;background:#0f1722;border:1px solid #2f3d52}
.af-a{margin-right:auto;background:#0f1722;border:1px solid #2f3d52}
.af-label{font-weight:700;font-size:.8rem;letter-spacing:.02em;opacity:.9;margin-bottom:.35rem;color:#b9d2ff}
.af-body{white-space:pre-wrap;word-wrap:break-word;color:#f5f7fa}
.af-body *{color:#f5f7fa !important}
.af-body pre,.af-body code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.af-body pre{background:#0e1116;color:#f5f5f5;padding:.6rem;border-radius:10px;overflow:auto}
.af-body table{border-collapse:collapse;width:auto;max-width:100%}
.af-body th,.af-body td{border:1px solid #46505f;padding:.35rem .5rem;text-align:left}
.af-sub{max-width:79ch;margin:.2rem 0 .5rem 0;background:#0b111a;border:1px solid #2f3d52;border-radius:12px;padding:.55rem .7rem;color:#f5f7fa;box-shadow:0 1px 6px rgba(0,0,0,.24)}
.af-sub-title{font-weight:700;font-size:.78rem;letter-spacing:.02em;color:#9fc3ff;margin-bottom:.25rem}
.af-sub-body{white-space:pre-wrap;word-wrap:break-word;color:#f5f7fa}
</style>
"""
            display(HTML(css))
            self.chat_css_loaded = True

        cls = "af-q" if role == "q" else "af-a"
        label = "Q" if role == "q" else "A"
        if markdown_enabled:
            try:
                import markdown as md  # type: ignore

                body_html = md.markdown(
                    text or "",
                    extensions=["fenced_code", "tables", "nl2br"],
                )
            except Exception:
                body_html = f"<div class='af-body'>{escape(text or '')}</div>"
        else:
            body_html = f"<div class='af-body'>{escape(text or '')}</div>"

        html = (
            f"<div class='af-chat'><div class='af-msg {cls}'>"
            f"<div class='af-label'>{label}</div>{body_html}</div></div>"
        )
        if display_id:
            if update:
                update_display(HTML(html), display_id=display_id)
            else:
                display(HTML(html), display_id=display_id)
        else:
            display(HTML(html))

    def _render_sub_box(self, title: str, body: str) -> None:
        """Render left-justified dark metadata/tokens box per Q/A combo."""
        try:
            from IPython.display import HTML, display  # type: ignore
        except Exception:
            print(f"{title}: {self._wrap(body)}")
            return
        safe_title = escape(title or "")
        safe_body = escape(body or "")
        html = (
            "<div class='af-chat'><div class='af-sub'>"
            f"<div class='af-sub-title'>{safe_title}</div>"
            f"<div class='af-sub-body'>{safe_body}</div>"
            "</div></div>"
        )
        display(HTML(html))

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

        self._render_chat_box("q", prompt, markdown_enabled=False)
        resp = requests.post(
            self.agentcore_url,
            headers=headers,
            data=payload,
            timeout=120,
            stream=True,
        )
        meta_text = (
            "runtimeSessionId={} statusCode={} contentType={}".format(
                self.session_id, resp.status_code, resp.headers.get("Content-Type", "unknown")
            )
        )
        self._render_sub_box("AgentCore metadata", meta_text)
        request_id = resp.headers.get("x-amzn-requestid") or resp.headers.get(
            "X-Amzn-RequestId"
        )

        model_info = None
        token_usage: dict[str, int | None] = {
            "input": None,
            "output": None,
            "total": None,
        }
        for k, v in resp.headers.items():
            lk = k.lower()
            if (
                model_info is None
                and any(x in lk for x in ("model", "inference", "profile"))
                and v
            ):
                model_info = f"{k}: {v}"

        parts: list[str] = []
        streamed_answer = ""
        live_answer_id = f"af-a-{uuid.uuid4().hex}"
        self._render_chat_box(
            "a",
            "Thinking...",
            markdown_enabled=True,
            display_id=live_answer_id,
            update=False,
        )
        last_ui = 0.0
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
                chunk = self._event_text(evt["event"])
                if chunk:
                    parts.append(chunk)
                    streamed_answer += chunk
                    now = time.time()
                    if now - last_ui >= 0.2:
                        self._render_chat_box(
                            "a",
                            streamed_answer,
                            markdown_enabled=True,
                            display_id=live_answer_id,
                            update=True,
                        )
                        last_ui = now

        answer = streamed_answer if streamed_answer else "".join(
            p for p in parts if p
        )
        self._render_chat_box(
            "a",
            answer,
            markdown_enabled=True,
            display_id=live_answer_id,
            update=True,
        )
        if (
            token_usage["total"] is None
            and token_usage["input"] is not None
            and token_usage["output"] is not None
        ):
            token_usage["total"] = int(token_usage["input"]) + int(
                token_usage["output"]
            )
        if any(v is not None for v in token_usage.values()):
            tok_text = "input={} output={} total={}".format(
                token_usage["input"] if token_usage["input"] is not None else "n/a",
                token_usage["output"] if token_usage["output"] is not None else "n/a",
                token_usage["total"] if token_usage["total"] is not None else "n/a",
            )
            self._render_sub_box("Token usage", tok_text)
        else:
            # AgentCore stream currently omits usage; fallback to Bedrock CountTokens.
            est_in, err_in = self._count_tokens_text(prompt, role="user")
            est_out, err_out = (
                self._count_tokens_text(answer, role="assistant")
                if answer
                else (None, None)
            )
            if est_in is not None or est_out is not None:
                est_total = (est_in or 0) + (est_out or 0)
                tok_text = (
                    "input={} output={} total={} source=bedrock:CountTokens estimate".format(
                        est_in if est_in is not None else "n/a",
                        est_out if est_out is not None else "n/a",
                        est_total if (est_in is not None or est_out is not None) else "n/a",
                    )
                )
                self._render_sub_box("Token usage", tok_text)
            else:
                self._render_sub_box("Token usage", "usage coming soon")
        if (not self.model_logged) and model_info:
            print(f"Model: {model_info}")
            self.model_logged = True
        self._print_realtime_invocation_metrics(
            request_id=request_id, session_id=self.session_id
        )

    def _print_realtime_invocation_metrics(
        self, request_id: str | None, session_id: str
    ) -> None:
        """Poll CloudWatch Bedrock invocation logs and print parsed metrics as soon as available."""
        group = self.cfg.get("invocation_log_group")
        if not group:
            return
        start_ms = int((time.time() - 120) * 1000)
        found: dict[str, Any] | None = None
        for wait_s in (1, 2, 4, 6):
            time.sleep(wait_s)
            try:
                # Use a broad fetch window then local matching because log field names vary.
                resp = self.logs.filter_log_events(
                    logGroupName=group,
                    startTime=start_ms,
                    interleaved=True,
                    limit=100,
                )
            except Exception as e:
                self._render_sub_box(
                    "Invocation metrics (real-time logs)",
                    f"unavailable ({e})",
                )
                return
            events = resp.get("events", [])
            for ev in reversed(events):
                msg = ev.get("message", "")
                if (
                    request_id
                    and request_id not in msg
                    and session_id not in msg
                ):
                    continue
                parsed = self._extract_invocation_metrics_from_log_message(msg)
                if parsed:
                    found = parsed
                    break
            if found:
                break
        if not found:
            self._render_sub_box(
                "Invocation metrics (real-time logs)",
                "not available yet",
            )
            return
        self._render_sub_box(
            "Invocation metrics (real-time logs)",
            "requestId={} modelId={} inputTokens={} outputTokens={} latencyMs={}".format(
                found.get("requestId", "n/a"),
                found.get("modelId", "n/a"),
                found.get("inputTokenCount", "n/a"),
                found.get("outputTokenCount", "n/a"),
                found.get("invocationLatency", "n/a"),
            ),
        )

    @staticmethod
    def _extract_invocation_metrics_from_log_message(
        message: str,
    ) -> dict[str, Any] | None:
        # Try JSON first.
        try:
            js = json.loads(message)

            def pick(*keys):
                for k in keys:
                    if k in js and js[k] is not None:
                        return js[k]
                return None

            out = {
                "requestId": pick("requestId", "RequestId", "requestID"),
                "modelId": pick("modelId", "ModelId"),
                "inputTokenCount": pick("inputTokenCount", "InputTokenCount"),
                "outputTokenCount": pick(
                    "outputTokenCount", "OutputTokenCount"
                ),
                "invocationLatency": pick(
                    "invocationLatency", "InvocationLatency", "latencyMs"
                ),
            }
            if any(v is not None for v in out.values()):
                return out
        except Exception:
            pass

        # Fallback regex parse for plain text log lines.
        patterns = {
            "requestId": r"(?:requestId|RequestId)[=:\\s\"]+([A-Za-z0-9-]{8,})",
            "modelId": r"(?:modelId|ModelId)[=:\\s\"]+([A-Za-z0-9._:-]+)",
            "inputTokenCount": r"(?:inputTokenCount|InputTokenCount)[=:\\s\"]+([0-9]+)",
            "outputTokenCount": r"(?:outputTokenCount|OutputTokenCount)[=:\\s\"]+([0-9]+)",
            "invocationLatency": r"(?:invocationLatency|InvocationLatency|latencyMs)[=:\\s\"]+([0-9]+)",
        }
        out: dict[str, Any] = {}
        for k, pat in patterns.items():
            m = re.search(pat, message)
            if m:
                out[k] = (
                    int(m.group(1))
                    if k
                    in (
                        "inputTokenCount",
                        "outputTokenCount",
                        "invocationLatency",
                    )
                    else m.group(1)
                )
        return out or None

    def _count_tokens_text(
        self, text: str, role: str
    ) -> tuple[int | None, str | None]:
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
                env["AWS_SECRET_ACCESS_KEY"] = self.credentials[
                    "SecretAccessKey"
                ]
                env["AWS_SESSION_TOKEN"] = self.credentials["SessionToken"]
            env["AWS_REGION"] = self.cfg["region"]
            proc = subprocess.run(
                self._aws_cmd()
                + [
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
                return None, (
                    err.splitlines()[-1]
                    if err
                    else "CountTokens command failed"
                )
            resp = json.loads(proc.stdout)
            if "inputTokens" in resp and resp["inputTokens"] is not None:
                return int(resp["inputTokens"]), None
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                return None, "aws CLI not installed in runtime"
            return None, str(e)
        return None, "empty CountTokens response"

    def verify_observability(self) -> None:
        print(f"Notebook runtime: {self.RUNTIME_VERSION}")
        self.ensure_fresh()
        pk = self.ssm_get(self.params["langfuse_pk"])
        sk = self.ssm_get(self.params["langfuse_sk"])
        base = self.ssm_get(self.params["langfuse_base_url"]).rstrip("/")
        arn = self.sts.get_caller_identity()["Arn"]
        print(f"Observability identity: {arn}")
        print(f"Success: retrieved Langfuse keys (PK: {pk[:7]}...)")
        def _probe(path: str, params: dict[str, Any] | None = None) -> requests.Response:
            return requests.get(
                f"{base}{path}",
                params=params or {},
                auth=(pk, sk),
                timeout=30,
            )

        def _pick_metric(
            row: dict[str, Any],
            measure: str,
            aggregation: str,
        ) -> Any:
            """Best-effort metric value extraction across API key naming variants."""
            direct = [
                f"{aggregation}_{measure}",
                f"{measure}_{aggregation}",
                f"{aggregation}{measure[0].upper()}{measure[1:]}",
                measure,
            ]
            for k in direct:
                if k in row and row[k] is not None:
                    return row[k]
            m = measure.lower()
            a = aggregation.lower()
            for k, v in row.items():
                lk = str(k).lower()
                if m in lk and a in lk and v is not None:
                    return v
            return None

        def _clean(v: Any, default: str = "-") -> str:
            if v is None:
                return default
            s = str(v).strip()
            if not s or s.lower() in ("none", "null", "nan"):
                return default
            return s

        def _pick_time_bucket(row: dict[str, Any]) -> Any:
            for key in (
                "timestampDay",
                "timeBucket",
                "time_bucket",
                "date",
                "day",
                "timestamp",
            ):
                if row.get(key) is not None:
                    return row.get(key)
            # metrics API may return unnamed dim columns
            for k, v in row.items():
                lk = str(k).lower()
                if "day" in lk or "time" in lk or "bucket" in lk:
                    return v
            return None

        def _pick_any_cost(row: dict[str, Any]) -> Any:
            # Direct known keys first
            for k in ("totalCost", "sum_totalCost", "cost", "value"):
                if row.get(k) is not None:
                    return row.get(k)
            # Fuzzy fallback
            for k, v in row.items():
                lk = str(k).lower()
                if "cost" in lk and v is not None:
                    return v
            return None

        auth = _probe("/api/public/projects")
        if auth.status_code == 200:
            print("Langfuse auth: 200 OK")
            projects = auth.json().get("data", [])
            if projects:
                p = projects[0]
                print(
                    "Langfuse project: id={} name={}".format(
                        p.get("id", "n/a"), p.get("name", "n/a")
                    )
                )
        else:
            print(f"Langfuse auth: HTTP {auth.status_code}")
            return

        # Capability probe matrix (schema-driven where possible).
        print("Langfuse capability check:")
        schema_paths = self._load_langfuse_openapi_paths()
        if schema_paths:
            print(
                "Langfuse OpenAPI loaded: paths={}".format(len(schema_paths))
            )
        else:
            print("Langfuse OpenAPI unavailable: using fallback probe set")

        wanted_checks = [
            ("traces.list", "/api/public/traces", {"limit": 1}),
            (
                "traces.by_session",
                "/api/public/traces",
                {"sessionId": self.session_id, "limit": 5},
            ),
            ("observations.list", "/api/public/observations", {"limit": 1}),
            ("sessions.list", "/api/public/sessions", {"limit": 1}),
            ("models.list", "/api/public/models", {"limit": 1}),
            ("metrics.v2", "/api/public/v2/metrics", {"limit": 1}),
            ("prompts.list", "/api/public/v2/prompts", {"limit": 1}),
            ("datasets.list", "/api/public/v2/datasets", {"limit": 1}),
            ("score.create", "/api/public/scores", {}),
        ]
        capability_checks = [
            (n, p, q)
            for (n, p, q) in wanted_checks
            if (not schema_paths) or (p in schema_paths)
        ]
        cap_results: dict[str, int] = {}
        for cap_name, cap_path, cap_params in capability_checks:
            try:
                r = _probe(cap_path, cap_params)
                cap_results[cap_name] = r.status_code
                print(f"  - {cap_name}: HTTP {r.status_code}")
            except Exception as e:
                cap_results[cap_name] = -1
                print(f"  - {cap_name}: error ({e})")

        traces = _probe(
            "/api/public/traces",
            {"sessionId": self.session_id, "limit": 5},
        )
        recent_fallback_traces: list[dict[str, Any]] = []
        if traces.status_code == 200:
            data = traces.json().get("data", [])
            print(
                "Langfuse traces: 200 OK (sessionId={} count={})".format(
                    self.session_id, len(data)
                )
            )
            page_info = traces.json().get("meta") or traces.json().get("pagination")
            if isinstance(page_info, dict):
                print(
                    "Langfuse pagination fields: "
                    + ", ".join(sorted(list(page_info.keys())))
                )
            if data:
                # Discover what this Langfuse project currently returns.
                trace_keys = sorted(list(data[0].keys()))
                print(f"Langfuse available trace fields: {', '.join(trace_keys)}")
                print("Langfuse trace preview:")
                for idx, t in enumerate(data[:3], start=1):
                    print(
                        "  [{}] id={} name={} sessionId={} ts={}".format(
                            idx,
                            t.get("id", "n/a"),
                            t.get("name", "n/a"),
                            t.get("sessionId", "n/a"),
                            t.get("timestamp", "n/a"),
                        )
                    )
                pretty = json.dumps(data[0], indent=2)[:2500]
                print("Langfuse latest trace (beautified JSON):")
                print(self._wrap(pretty, width=79))
                trace_id = data[0].get("id")
                if trace_id:
                    detail = _probe(f"/api/public/traces/{trace_id}")
                    if detail.status_code == 200:
                        print("Langfuse trace detail: 200 OK")
                        detail_obj = detail.json()
                        detail_data = detail_obj.get("data", detail_obj)
                        if isinstance(detail_data, dict):
                            dkeys = sorted(list(detail_data.keys()))
                            print(
                                "Langfuse available trace-detail fields: "
                                + ", ".join(dkeys)
                            )
                            obs = detail_data.get("observations")
                            if isinstance(obs, list):
                                print(f"Langfuse observations: count={len(obs)}")
                                if obs:
                                    okeys = sorted(list(obs[0].keys()))
                                    print(
                                        "Langfuse available observation fields: "
                                        + ", ".join(okeys)
                                    )
                            # Probe per-observation endpoint if IDs are present.
                            if obs and isinstance(obs, list):
                                obs_id = obs[0].get("id")
                                if obs_id:
                                    obs_detail = _probe(
                                        f"/api/public/observations/{obs_id}"
                                    )
                                    print(
                                        "Langfuse observation detail: HTTP {}".format(
                                            obs_detail.status_code
                                        )
                                    )
                    else:
                        print(f"Langfuse trace detail: HTTP {detail.status_code}")
            else:
                # Helpful fallback when sessionId has not propagated yet.
                recent = _probe("/api/public/traces", {"limit": 3})
                if recent.status_code == 200:
                    rdata = recent.json().get("data", [])
                    if rdata:
                        recent_fallback_traces = [
                            x for x in rdata if isinstance(x, dict)
                        ]
                        print("Langfuse recent traces fallback:")
                        for idx, t in enumerate(rdata[:3], start=1):
                            print(
                                "  [{}] id={} name={} sessionId={} ts={}".format(
                                    idx,
                                    t.get("id", "n/a"),
                                    t.get("name", "n/a"),
                                    t.get("sessionId", "n/a"),
                                    t.get("timestamp", "n/a"),
                                )
                            )
        else:
            print(f"Langfuse traces: HTTP {traces.status_code}")

        # Comments: fetch latest comments for collaboration context.
        comments_resp = _probe("/api/public/comments", {"limit": 5, "page": 1})
        comments_data: list[dict[str, Any]] = []
        if comments_resp.status_code == 200:
            comments_data = [
                x
                for x in comments_resp.json().get("data", [])
                if isinstance(x, dict)
            ]
            print(f"Langfuse comments: 200 OK count={len(comments_data)}")
            for c in comments_data[:3]:
                print(
                    "  - id={} objectType={} objectId={} author={} ts={}".format(
                        c.get("id", "-"),
                        c.get("objectType", "-"),
                        c.get("objectId", "-"),
                        c.get("authorUserId", "-"),
                        c.get("createdAt", "-"),
                    )
                )
        else:
            print(f"Langfuse comments: HTTP {comments_resp.status_code}")

        # Dashboard-like metrics snapshot (last 24h) via v2 metrics API.
        try:
            now = datetime.now(timezone.utc)
            frm = now - timedelta(hours=24)
            metrics_query = {
                "view": "observations",
                "metrics": [
                    {"measure": "count", "aggregation": "count"},
                    {"measure": "latency", "aggregation": "p95"},
                    {"measure": "totalTokens", "aggregation": "sum"},
                    {"measure": "totalCost", "aggregation": "sum"},
                ],
                "fromTimestamp": frm.isoformat().replace("+00:00", "Z"),
                "toTimestamp": now.isoformat().replace("+00:00", "Z"),
            }
            m = _probe(
                "/api/public/v2/metrics",
                {"query": json.dumps(metrics_query, separators=(",", ":"))},
            )
            if m.status_code == 200:
                m_js = m.json()
                rows = m_js.get("data", [])
                print(f"Langfuse metrics(v2): 200 OK rows={len(rows)}")
                if rows:
                    first = rows[0]
                    obs_count = _pick_metric(first, "count", "count")
                    p95_lat = _pick_metric(first, "latency", "p95")
                    tot_tokens = _pick_metric(first, "totalTokens", "sum")
                    tot_cost = _pick_metric(first, "totalCost", "sum")
                    print(
                        "Langfuse metrics summary (24h): "
                        f"observations={obs_count} p95_latency_ms={p95_lat} "
                        f"total_tokens={tot_tokens} total_cost_usd={tot_cost}"
                    )
            else:
                print(f"Langfuse metrics(v2): HTTP {m.status_code}")

            # Daily cost time series (last 7 days).
            frm_7d = now - timedelta(days=7)
            daily_cost_query = {
                "view": "observations",
                "metrics": [
                    {"measure": "totalCost", "aggregation": "sum"},
                ],
                "timeDimension": {"granularity": "day"},
                "fromTimestamp": frm_7d.isoformat().replace("+00:00", "Z"),
                "toTimestamp": now.isoformat().replace("+00:00", "Z"),
            }
            m_daily = _probe(
                "/api/public/v2/metrics",
                {"query": json.dumps(daily_cost_query, separators=(",", ":"))},
            )
            if m_daily.status_code == 200:
                drows = m_daily.json().get("data", [])
                print(f"Langfuse daily cost(v2): 200 OK rows={len(drows)}")
                for i, r in enumerate(drows[:7], start=1):
                    day = _pick_time_bucket(r)
                    cost = _pick_metric(r, "totalCost", "sum")
                    if cost is None:
                        cost = _pick_any_cost(r)
                    print(
                        f"  - day={_clean(day, str(i))} total_cost_usd={_clean(cost, '0')}"
                    )
            else:
                print(f"Langfuse daily cost(v2): HTTP {m_daily.status_code}")

            # Cost by model (last 7 days).
            by_model_query = {
                "view": "observations",
                "metrics": [
                    {"measure": "totalCost", "aggregation": "sum"},
                    {"measure": "count", "aggregation": "count"},
                ],
                "dimensions": [{"field": "providedModelName"}],
                "fromTimestamp": frm_7d.isoformat().replace("+00:00", "Z"),
                "toTimestamp": now.isoformat().replace("+00:00", "Z"),
            }
            m_model = _probe(
                "/api/public/v2/metrics",
                {"query": json.dumps(by_model_query, separators=(",", ":"))},
            )
            if m_model.status_code == 200:
                mrows = m_model.json().get("data", [])
                print(f"Langfuse cost by model(v2): 200 OK rows={len(mrows)}")
                for r in mrows[:10]:
                    model = (
                        r.get("providedModelName")
                        or r.get("observationModelName")
                        or r.get("model")
                        or "n/a"
                    )
                    cost = _pick_metric(r, "totalCost", "sum")
                    count = _pick_metric(r, "count", "count")
                    print(
                        "  - model={} total_cost_usd={} observations={}".format(
                            _clean(model),
                            _clean(cost, "0"),
                            _clean(count, "0"),
                        )
                    )
            else:
                print(f"Langfuse cost by model(v2): HTTP {m_model.status_code}")

            # Fallback: aggregate cost/tokens from raw observations.
            obs = _probe("/api/public/v2/observations", {"limit": 200})
            if obs.status_code >= 400:
                # Compatibility fallback for older projects/routes and query variants.
                obs = _probe("/api/public/observations", {"page": 1, "limit": 200})
            if obs.status_code >= 400:
                obs = _probe("/api/public/observations", {})
            if obs.status_code == 200:
                orows = obs.json().get("data", [])
                total_cost = 0.0
                total_tokens = 0
                priced_rows = 0
                token_rows = 0
                for row in orows:
                    if not isinstance(row, dict):
                        continue
                    # Handle common cost key variants across versions.
                    cost_candidates = [
                        row.get("totalCost"),
                        row.get("cost"),
                        (row.get("usage") or {}).get("totalCost")
                        if isinstance(row.get("usage"), dict)
                        else None,
                    ]
                    cval = next(
                        (
                            float(v)
                            for v in cost_candidates
                            if isinstance(v, (int, float, str)) and str(v) not in ("", "None")
                        ),
                        None,
                    )
                    if cval is not None:
                        total_cost += cval
                        priced_rows += 1

                    usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
                    tok_candidates = [
                        row.get("totalTokens"),
                        usage.get("totalTokens"),
                        usage.get("inputTokens"),
                        usage.get("outputTokens"),
                    ]
                    tval = next(
                        (
                            int(float(v))
                            for v in tok_candidates
                            if isinstance(v, (int, float, str)) and str(v) not in ("", "None")
                        ),
                        None,
                    )
                    if tval is not None:
                        total_tokens += tval
                        token_rows += 1

                print(
                    "Langfuse observations fallback: 200 OK rows={} rows_with_cost={} rows_with_tokens={} total_cost_usd={} total_tokens={}".format(
                        len(orows),
                        priced_rows,
                        token_rows,
                        round(total_cost, 6),
                        total_tokens,
                    )
                )
                if priced_rows == 0:
                    print(
                        "Cost note: no per-observation cost found in Langfuse data. "
                        "Enable/verify model price mapping or send usage+cost with generations."
                    )
            else:
                snippet = ""
                try:
                    snippet = (obs.text or "")[:220].replace("\n", " ")
                except Exception:
                    snippet = ""
                if snippet:
                    print(
                        f"Langfuse observations fallback: HTTP {obs.status_code} body={snippet}"
                    )
                else:
                    print(f"Langfuse observations fallback: HTTP {obs.status_code}")
        except Exception as e:
            print(f"Langfuse metrics(v2): error ({e})")

        # If no usage/cost is present, emit a synthetic verification generation
        # so end-to-end metrics/cost plumbing can be validated immediately.
        try:
            need_seed = (
                ("obs" in locals() and isinstance(obs, requests.Response) and obs.status_code == 200)
                and ("priced_rows" in locals() and int(priced_rows) == 0)
                and ("token_rows" in locals() and int(token_rows) == 0)
            )
            if need_seed:
                from langfuse import get_client, propagate_attributes

                os.environ["LANGFUSE_PUBLIC_KEY"] = pk
                os.environ["LANGFUSE_SECRET_KEY"] = sk
                os.environ["LANGFUSE_BASE_URL"] = base

                lf = get_client()
                with propagate_attributes(
                    session_id=self.session_id,
                    metadata={"source": "notebook-observability-seed"},
                ):
                    with lf.start_as_current_observation(
                        as_type="generation",
                        name="notebook-usage-cost-seed",
                        model=self.cfg.get("model_id", "unknown-model"),
                        input={"purpose": "seed_usage_cost"},
                    ) as gen:
                        gen.update(
                            output={"status": "seeded"},
                            usage_details={"input": 12, "output": 34, "total": 46},
                            cost_details={
                                "input": 0.00012,
                                "output": 0.00068,
                                "total": 0.0008,
                            },
                        )
                lf.flush()
                time.sleep(2)
                print(
                    "Langfuse seed generation emitted with usage/cost for validation."
                )
                # Quick re-check of metrics after seed event.
                now2 = datetime.now(timezone.utc)
                frm2 = now2 - timedelta(hours=24)
                m2_query = {
                    "view": "observations",
                    "metrics": [
                        {"measure": "count", "aggregation": "count"},
                        {"measure": "totalTokens", "aggregation": "sum"},
                        {"measure": "totalCost", "aggregation": "sum"},
                    ],
                    "fromTimestamp": frm2.isoformat().replace("+00:00", "Z"),
                    "toTimestamp": now2.isoformat().replace("+00:00", "Z"),
                }
                m2 = _probe(
                    "/api/public/v2/metrics",
                    {"query": json.dumps(m2_query, separators=(",", ":"))},
                )
                if m2.status_code == 200:
                    rows2 = m2.json().get("data", [])
                    if rows2:
                        r2 = rows2[0]
                        print(
                            "Langfuse post-seed metrics (24h): observations={} total_tokens={} total_cost_usd={}".format(
                                _clean(_pick_metric(r2, "count", "count"), "0"),
                                _clean(_pick_metric(r2, "totalTokens", "sum"), "0"),
                                _clean(_pick_metric(r2, "totalCost", "sum"), "0"),
                            )
                        )
                # Immediate verification via observations endpoint (faster than metrics aggregation).
                obs_seed = _probe(
                    "/api/public/observations",
                    {"name": "notebook-usage-cost-seed", "limit": 5, "page": 1},
                )
                if obs_seed.status_code == 200:
                    srows = obs_seed.json().get("data", [])
                    if srows:
                        s = srows[0]
                        usage = s.get("usage") if isinstance(s.get("usage"), dict) else {}
                        total_tokens = (
                            s.get("totalTokens")
                            or usage.get("totalTokens")
                            or usage.get("inputTokens")
                            or 0
                        )
                        total_cost = (
                            s.get("totalCost")
                            or (usage.get("totalCost") if isinstance(usage, dict) else None)
                            or 0
                        )
                        print(
                            "Langfuse seed observation check: 200 OK id={} total_tokens={} total_cost_usd={}".format(
                                s.get("id", "-"),
                                total_tokens,
                                total_cost,
                            )
                        )
                    else:
                        print("Langfuse seed observation check: 200 OK but no rows yet")
                else:
                    print(
                        f"Langfuse seed observation check: HTTP {obs_seed.status_code}"
                    )
        except Exception as e:
            print(f"Langfuse seed generation skipped: {e}")

        # Optional: auto-create collaboration comment on latest trace.
        # Enable by setting LANGFUSE_AUTO_COMMENT=1 in runtime.
        if os.getenv("LANGFUSE_AUTO_COMMENT", "0") == "1":
            target_trace_id = None
            try:
                cur_traces = traces.json().get("data", []) if traces.status_code == 200 else []
                if cur_traces and isinstance(cur_traces[0], dict):
                    target_trace_id = cur_traces[0].get("id")
                if not target_trace_id and recent_fallback_traces:
                    target_trace_id = recent_fallback_traces[0].get("id")
                if target_trace_id:
                    payload = {
                        "projectId": auth.json().get("data", [{}])[0].get("id"),
                        "objectType": "trace",
                        "objectId": target_trace_id,
                        "content": (
                            f"Automated notebook observability check for session "
                            f"{self.session_id}."
                        ),
                    }
                    cpost = requests.post(
                        f"{base}/api/public/comments",
                        auth=(pk, sk),
                        json=payload,
                        timeout=30,
                    )
                    print(f"Langfuse auto-comment: HTTP {cpost.status_code}")
            except Exception as e:
                print(f"Langfuse auto-comment: error ({e})")

        # Persist a real observability report artifact from live API responses.
        try:
            report = {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "sessionId": self.session_id,
                "baseUrl": base,
                "identityArn": arn,
                "projectsStatus": auth.status_code,
                "tracesStatus": traces.status_code,
                "projects": auth.json().get("data", [])
                if auth.status_code == 200
                else [],
                "traces": traces.json().get("data", [])
                if traces.status_code == 200
                else [],
                "capabilityHttp": cap_results,
                "metrics24h": m.json() if "m" in locals() and m.status_code == 200 else {},
                "metricsDaily": m_daily.json()
                if "m_daily" in locals() and m_daily.status_code == 200
                else {},
                "metricsByModel": m_model.json()
                if "m_model" in locals() and m_model.status_code == 200
                else {},
                "commentsStatus": comments_resp.status_code,
                "comments": comments_data,
            }
            out_dir = Path("artifacts") / "langfuse"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            report_json = out_dir / f"notebook_observability_{ts}.json"
            report_json.write_text(
                json.dumps(report, indent=2),
                encoding="utf-8",
            )
            latest = out_dir / "notebook_observability_latest.json"
            latest.write_text(json.dumps(report, indent=2), encoding="utf-8")

            traces_csv = out_dir / "notebook_traces_latest.csv"
            rows = report.get("traces", [])
            if isinstance(rows, list) and rows:
                keys: set[str] = set()
                for row in rows:
                    if isinstance(row, dict):
                        keys.update(row.keys())
                cols = sorted(list(keys))
                lines = [",".join(cols)]
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    vals = []
                    for c in cols:
                        v = row.get(c, "")
                        if isinstance(v, (dict, list)):
                            v = json.dumps(v, separators=(",", ":"))
                        s = str(v).replace('"', '""')
                        vals.append(f'"{s}"')
                    lines.append(",".join(vals))
                traces_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")

            print(f"Observability report saved: {report_json}")
            print(f"Observability report latest: {latest}")
            if traces_csv.exists():
                print(f"Observability traces CSV: {traces_csv}")
        except Exception as e:
            print(f"Observability report export failed: {e}")

    def _langfuse_auth_context(self) -> tuple[str, str, str]:
        """Return (public_key, secret_key, base_url) from SSM."""
        self.ensure_fresh()
        pk = self.ssm_get(self.params["langfuse_pk"])
        sk = self.ssm_get(self.params["langfuse_sk"])
        base = self.ssm_get(self.params["langfuse_base_url"]).rstrip("/")
        return pk, sk, base

    def create_langfuse_comment(
        self,
        object_type: str,
        object_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Create a Langfuse comment on trace/observation/session/prompt."""
        pk, sk, base = self._langfuse_auth_context()
        projects = requests.get(
            f"{base}/api/public/projects",
            auth=(pk, sk),
            timeout=30,
        )
        if projects.status_code != 200:
            return {"ok": False, "status": projects.status_code, "error": "project lookup failed"}
        project_id = (projects.json().get("data", [{}])[0] or {}).get("id")
        payload = {
            "projectId": project_id,
            "objectType": object_type,
            "objectId": object_id,
            "content": content[:4000],
        }
        resp = requests.post(
            f"{base}/api/public/comments",
            auth=(pk, sk),
            json=payload,
            timeout=30,
        )
        out = {"ok": resp.status_code == 200, "status": resp.status_code}
        try:
            out["data"] = resp.json()
        except Exception:
            out["text"] = (resp.text or "")[:300]
        return out

    def create_langfuse_score(
        self,
        trace_id: str,
        name: str,
        value: Any,
        data_type: str | None = None,
        comment: str | None = None,
        observation_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a Langfuse score (feedback/correction/etc)."""
        pk, sk, base = self._langfuse_auth_context()
        payload: dict[str, Any] = {
            "traceId": trace_id,
            "name": name,
            "value": value,
        }
        if data_type:
            payload["dataType"] = data_type
        if comment:
            payload["comment"] = comment
        if observation_id:
            payload["observationId"] = observation_id
        resp = requests.post(
            f"{base}/api/public/scores",
            auth=(pk, sk),
            json=payload,
            timeout=30,
        )
        out = {"ok": resp.status_code == 200, "status": resp.status_code}
        try:
            out["data"] = resp.json()
        except Exception:
            out["text"] = (resp.text or "")[:300]
        return out

    def create_langfuse_correction(
        self,
        trace_id: str,
        corrected_output: str,
        observation_id: str | None = None,
    ) -> dict[str, Any]:
        """Create corrected output score (dataType=CORRECTION, name=output)."""
        return self.create_langfuse_score(
            trace_id=trace_id,
            observation_id=observation_id,
            name="output",
            value=corrected_output,
            data_type="CORRECTION",
        )

    def create_langfuse_user_feedback(
        self,
        trace_id: str,
        score_value: float,
        comment: str | None = None,
        name: str = "user-feedback",
    ) -> dict[str, Any]:
        """Create explicit user feedback score for a trace."""
        return self.create_langfuse_score(
            trace_id=trace_id,
            name=name,
            value=score_value,
            comment=comment,
        )

    def _load_langfuse_openapi_paths(self) -> set[str]:
        """Fetch Langfuse OpenAPI YAML and extract path keys."""
        urls = [
            "https://cloud.langfuse.com/generated/api/openapi.yml",
            "https://us.cloud.langfuse.com/generated/api/openapi.yml",
        ]
        txt = ""
        for u in urls:
            try:
                r = requests.get(u, timeout=30)
                if r.status_code == 200 and "openapi:" in r.text:
                    txt = r.text
                    break
            except Exception:
                continue
        if not txt:
            return set()
        paths: set[str] = set()
        in_paths = False
        for line in txt.splitlines():
            if line.strip() == "paths:":
                in_paths = True
                continue
            if not in_paths:
                continue
            if not line.startswith("  "):
                # end of paths section
                break
            m = re.match(r"^\s{2}(/api/public[^\s:]*):\s*$", line)
            if m:
                paths.add(m.group(1))
        return paths
