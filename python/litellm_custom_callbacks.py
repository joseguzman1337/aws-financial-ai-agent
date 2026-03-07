"""Optional LiteLLM custom callback wiring with safe async hooks.

This module is additive and does not change existing LangChain/Bedrock flow.
Use it when invoking models through LiteLLM.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _artifact_dir() -> Path:
    out = Path("artifacts") / "litellm"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _append_jsonl(event: dict[str, Any]) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = _artifact_dir() / f"litellm_callbacks_{ts}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _cost_from_kwargs(kwargs: dict[str, Any]) -> float | None:
    try:
        v = kwargs.get("response_cost")
        return float(v) if v is not None else None
    except Exception:
        return None


def _duration_ms(start_time: Any, end_time: Any) -> int | None:
    try:
        return int((end_time - start_time).total_seconds() * 1000)
    except Exception:
        return None


def _base_event(
    hook: str,
    kwargs: dict[str, Any] | None,
    start_time: Any,
    end_time: Any,
) -> dict[str, Any]:
    kw = kwargs or {}
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "hook": hook,
        "model": kw.get("model"),
        "response_cost": _cost_from_kwargs(kw),
        "cache_hit": kw.get("cache_hit"),
        "duration_ms": _duration_ms(start_time, end_time),
        "metadata": kw.get("litellm_params", {}).get("metadata", {}),
    }


def register_litellm_callbacks() -> bool:
    """Register safe custom callbacks if litellm is installed.

    Returns True when callbacks are active, False when LiteLLM is unavailable.
    """
    try:
        import litellm
        from litellm.integrations.custom_logger import CustomLogger
    except Exception:
        return False

    class SafeCustomHandler(CustomLogger):
        def log_pre_api_call(self, model, messages, kwargs):
            _append_jsonl(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "hook": "pre_api_call",
                    "model": model,
                    "message_count": len(messages or []),
                }
            )

        def log_post_api_call(self, kwargs, response_obj, start_time, end_time):
            _append_jsonl(
                _base_event("post_api_call", kwargs, start_time, end_time)
            )

        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            event = _base_event("success", kwargs, start_time, end_time)
            _append_jsonl(event)

        def log_failure_event(self, kwargs, response_obj, start_time, end_time):
            event = _base_event("failure", kwargs, start_time, end_time)
            _append_jsonl(event)

        async def async_log_success_event(
            self, kwargs, response_obj, start_time, end_time
        ):
            event = _base_event("async_success", kwargs, start_time, end_time)
            _append_jsonl(event)

        async def async_log_failure_event(
            self, kwargs, response_obj, start_time, end_time
        ):
            event = _base_event("async_failure", kwargs, start_time, end_time)
            _append_jsonl(event)

    # Optional functional callbacks for input/success/failure hooks.
    def input_callback(kwargs, *args, **_kwargs):
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "hook": "input_callback",
            "model": (kwargs or {}).get("model"),
        }
        _append_jsonl(event)

    def success_callback(kwargs, completion_response, start_time, end_time):
        event = _base_event("success_callback", kwargs, start_time, end_time)
        _append_jsonl(event)

    def failure_callback(kwargs, completion_response, start_time, end_time):
        event = _base_event("failure_callback", kwargs, start_time, end_time)
        _append_jsonl(event)

    litellm.callbacks = [SafeCustomHandler()]
    litellm.input_callback = [input_callback]
    litellm.success_callback = [success_callback]
    litellm.failure_callback = [failure_callback]

    if os.getenv("LITELLM_VERBOSE_CALLBACKS", "0") == "1":
        # Lightweight indicator only when explicitly enabled.
        print(f"LiteLLM callbacks active at {int(time.time())}")
    return True

