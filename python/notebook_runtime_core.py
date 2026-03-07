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
    ) -> None:
        """Render Q/A boxes in notebooks with markdown support."""
        try:
            from IPython.display import HTML, display  # type: ignore
        except Exception:
            prefix = "Q" if role == "q" else "A"
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
        self._render_chat_box("a", answer, markdown_enabled=True)
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
                print(
                    f"Invocation metrics (real-time logs): unavailable ({e})"
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
            print("Invocation metrics (real-time logs): not available yet")
            return
        print(
            "Invocation metrics (real-time logs): requestId={} modelId={} inputTokens={} outputTokens={} latencyMs={}".format(
                found.get("requestId", "n/a"),
                found.get("modelId", "n/a"),
                found.get("inputTokenCount", "n/a"),
                found.get("outputTokenCount", "n/a"),
                found.get("invocationLatency", "n/a"),
            )
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
        self.ensure_fresh()
        pk = self.ssm_get(self.params["langfuse_pk"])
        sk = self.ssm_get(self.params["langfuse_sk"])
        base = self.ssm_get(self.params["langfuse_base_url"]).rstrip("/")
        arn = self.sts.get_caller_identity()["Arn"]
        print(f"Observability identity: {arn}")
        print(f"Success: retrieved Langfuse keys (PK: {pk[:7]}...)")
        auth = requests.get(
            f"{base}/api/public/projects", auth=(pk, sk), timeout=30
        )
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
        traces = requests.get(
            f"{base}/api/public/traces",
            params={"sessionId": self.session_id, "limit": 5},
            auth=(pk, sk),
            timeout=30,
        )
        if traces.status_code == 200:
            data = traces.json().get("data", [])
            print(
                "Langfuse traces: 200 OK (sessionId={} count={})".format(
                    self.session_id, len(data)
                )
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
                    detail = requests.get(
                        f"{base}/api/public/traces/{trace_id}",
                        auth=(pk, sk),
                        timeout=30,
                    )
                    if detail.status_code == 200:
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
                    else:
                        print(f"Langfuse trace detail: HTTP {detail.status_code}")
        else:
            print(f"Langfuse traces: HTTP {traces.status_code}")
