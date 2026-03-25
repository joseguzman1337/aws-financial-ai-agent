"""
This module serves the FastAPI application for the Financial AI Agent.
"""

print("--- CONTAINER STARTING ---")
import json
import logging
import os
import re
import sys
import uuid

from agent import get_agent_graph
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from langfuse import propagate_attributes
from langfuse_config import ensure_langfuse_env, get_langfuse_client
from langfuse.langchain import CallbackHandler

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = FastAPI()

logger.info("FastAPI application initialized.")

_ENV_RE = re.compile(r"^(?!langfuse)[a-z0-9-_]{1,40}$")
_META_KEY_RE = re.compile(r"^[A-Za-z0-9]+$")
_TRACE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_LEVELS = {"DEBUG", "DEFAULT", "WARNING", "ERROR"}
_OBS_TYPES = {
    "event",
    "span",
    "generation",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "embedding",
    "guardrail",
}


def _resolve_langfuse_environment(payload: dict, request: Request) -> str:
    """Resolve and validate Langfuse tracing environment."""
    env = (
        payload.get("tracing_environment")
        or request.headers.get("X-Langfuse-Environment")
        or os.getenv("LANGFUSE_TRACING_ENVIRONMENT")
        or "default"
    )
    env = str(env).strip().lower()
    if _ENV_RE.match(env):
        return env
    logger.warning(
        "Invalid LANGFUSE environment '%s'; falling back to 'default'.",
        env,
    )
    return "default"


def _resolve_langfuse_tags(payload: dict, request: Request) -> list[str]:
    """Resolve, sanitize, and cap Langfuse tags."""
    raw = payload.get("langfuse_tags")
    if raw is None:
        header = request.headers.get("X-Langfuse-Tags", "")
        raw = [x.strip() for x in header.split(",") if x.strip()] if header else []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for t in raw:
        s = str(t).strip()
        if not s:
            continue
        if len(s) > 200:
            continue
        out.append(s)
    return out[:20]


def _resolve_langfuse_metadata(payload: dict) -> dict[str, str]:
    """Resolve propagated metadata with Langfuse-safe key/value constraints."""
    raw = payload.get("langfuse_metadata")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        ks = str(k).strip()
        if (not ks) or (not _META_KEY_RE.match(ks)):
            continue
        vs = str(v).strip()
        if not vs or len(vs) > 200:
            continue
        out[ks] = vs
    return out


def _resolve_external_trace_seed(payload: dict, request: Request) -> str | None:
    """Resolve external correlation ID used to derive/propagate Langfuse trace_id."""
    for key in ("langfuse_trace_id", "trace_id", "correlation_id", "request_id"):
        if payload.get(key):
            return str(payload.get(key)).strip()
    for h in ("X-Trace-Id", "X-Correlation-Id", "X-Request-Id"):
        hv = request.headers.get(h)
        if hv:
            return hv.strip()
    return None


def _resolve_log_level(payload: dict, request: Request) -> str:
    level = (
        payload.get("langfuse_level")
        or request.headers.get("X-Langfuse-Level")
        or "DEFAULT"
    )
    lv = str(level).strip().upper()
    return lv if lv in _LEVELS else "DEFAULT"


def _resolve_status_message(payload: dict, request: Request) -> str | None:
    msg = payload.get("langfuse_status_message") or request.headers.get(
        "X-Langfuse-Status-Message"
    )
    if msg is None:
        return None
    txt = str(msg).strip()
    return txt[:500] if txt else None


def _resolve_observation_type(payload: dict, request: Request) -> str:
    raw = payload.get("langfuse_observation_type") or request.headers.get(
        "X-Langfuse-Observation-Type"
    )
    t = str(raw).strip().lower() if raw is not None else "span"
    return t if t in _OBS_TYPES else "span"


def _resolve_release(payload: dict, request: Request) -> str | None:
    release = (
        payload.get("langfuse_release")
        or request.headers.get("X-Langfuse-Release")
        or os.getenv("LANGFUSE_RELEASE")
    )
    if release is None:
        return None
    txt = str(release).strip()
    return txt[:120] if txt else None


def _resolve_version(payload: dict, request: Request) -> str | None:
    version = payload.get("langfuse_version") or request.headers.get(
        "X-Langfuse-Version"
    )
    if version is None:
        return None
    txt = str(version).strip()
    return txt[:60] if txt else None


def _resolve_numeric_map(payload: dict, key: str) -> dict[str, float]:
    raw = payload.get(key)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except Exception:
            continue
    return out


def _resolve_bool(payload: dict, request: Request, key: str, header: str) -> bool:
    raw = payload.get(key)
    if raw is None:
        raw = request.headers.get(header)
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _resolve_trace_name(payload: dict, request: Request) -> str | None:
    raw = payload.get("langfuse_trace_name") or request.headers.get(
        "X-Langfuse-Trace-Name"
    )
    if raw is None:
        return None
    txt = str(raw).strip()
    return txt[:120] if txt else None


@app.on_event("shutdown")
async def flush_langfuse():
    """Flush Langfuse events on graceful shutdown."""
    if ensure_langfuse_env():
        try:
            get_langfuse_client().flush()
        except Exception as error:  # pragma: no cover
            logger.warning("Langfuse flush failed: %s", str(error))


@app.post("/invocations")
async def invoke_agent(request: Request):
    """
    Handle POST requests for agent invocations, supporting streaming.
    """
    session_id = request.headers.get(
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", str(uuid.uuid4())
    )
    user_id = request.headers.get("X-User-Id")
    logger.info("Invocation received. Session ID: %s", session_id)

    try:
        payload = await request.json()
        query = payload.get("prompt")
        # Prefer explicit payload user_id over header if provided.
        if payload.get("user_id"):
            user_id = str(payload.get("user_id"))
        tracing_environment = _resolve_langfuse_environment(payload, request)
        langfuse_tags = _resolve_langfuse_tags(payload, request)
        langfuse_metadata = _resolve_langfuse_metadata(payload)
        external_trace_seed = _resolve_external_trace_seed(payload, request)
        log_level = _resolve_log_level(payload, request)
        status_message = _resolve_status_message(payload, request)
        observation_type = _resolve_observation_type(payload, request)
        release = _resolve_release(payload, request)
        version = _resolve_version(payload, request)
        usage_details = _resolve_numeric_map(payload, "langfuse_usage_details")
        cost_details = _resolve_numeric_map(payload, "langfuse_cost_details")
        as_baggage = _resolve_bool(
            payload,
            request,
            "langfuse_as_baggage",
            "X-Langfuse-As-Baggage",
        )
        trace_name = _resolve_trace_name(payload, request)
        logger.info("Query: %s", query)

        langfuse_enabled = ensure_langfuse_env()
        callbacks = []
        trace_context = {}
        if langfuse_enabled:
            if external_trace_seed:
                if _TRACE_ID_RE.match(external_trace_seed):
                    trace_context = {"trace_id": external_trace_seed}
                else:
                    try:
                        trace_id = get_langfuse_client().create_trace_id(
                            seed=external_trace_seed
                        )
                        trace_context = {"trace_id": trace_id}
                    except Exception:
                        trace_context = {}
            langfuse_handler = CallbackHandler(
                trace_context=trace_context,
                environment=tracing_environment,
                version=version,
            )
            callbacks = [langfuse_handler]
        else:
            logger.warning(
                "Langfuse keys unavailable; invocation will run without tracing."
            )

        agent_input = {"messages": [("user", query)]}
        config = {
            "callbacks": callbacks,
            "metadata": {
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
                "langfuse_environment": tracing_environment,
                "langfuse_tags": langfuse_tags,
                "langfuse_metadata": langfuse_metadata,
                "langfuse_trace_seed": external_trace_seed,
                "langfuse_level": log_level,
                "langfuse_status_message": status_message,
                "langfuse_observation_type": observation_type,
                "langfuse_release": release,
                "langfuse_version": version,
                "langfuse_usage_keys": sorted(list(usage_details.keys())),
                "langfuse_cost_keys": sorted(list(cost_details.keys())),
                "langfuse_as_baggage": as_baggage,
                "langfuse_trace_name": trace_name,
                "agent_runtime": "Financial_Analyst_Agent",
                "has_prompt": bool(query),
            },
            "recursion_limit": 25,
        }

        async def stream_generator():
            try:
                langfuse = get_langfuse_client() if langfuse_enabled else None
                if langfuse:
                    with langfuse.start_as_current_observation(
                        as_type=observation_type,
                        name="agentcore-invocation",
                        trace_context=trace_context,
                        level=log_level,
                        status_message=status_message,
                        version=version,
                        input={
                            "session_id": session_id,
                            "user_id": user_id,
                            "environment": tracing_environment,
                            "release": release,
                            "version": version,
                            "trace_seed": external_trace_seed,
                            "tags": langfuse_tags,
                            "metadata": langfuse_metadata,
                            "trace_name": trace_name,
                            "prompt": query,
                        },
                    ) as span:
                        with propagate_attributes(
                            session_id=session_id,
                            user_id=user_id,
                            environment=tracing_environment,
                            version=version,
                            tags=langfuse_tags,
                            metadata=langfuse_metadata,
                            trace_name=trace_name,
                            as_baggage=as_baggage,
                        ):
                            result = await get_agent_graph().ainvoke(
                                agent_input, config=config
                            )
                        span.update(
                            output={"status": "ok"},
                            level=log_level,
                            status_message=status_message or "Invocation completed",
                            usage_details=usage_details if usage_details else None,
                            cost_details=cost_details if cost_details else None,
                        )
                        try:
                            trace_id = langfuse.get_current_trace_id()
                            trace_url = langfuse.get_trace_url(trace_id=trace_id)
                            yield f"data: {json.dumps({'trace_id': trace_id, 'trace_url': trace_url})}\n\n"
                        except Exception:
                            pass
                else:
                    result = await get_agent_graph().ainvoke(
                        agent_input, config=config
                    )
                messages = result.get("messages", [])
                for msg in reversed(messages):
                    content = getattr(msg, "content", None)
                    if content and getattr(msg, "type", None) == "ai":
                        chunk_data = {"event": content}
                        yield f"data: {json.dumps(chunk_data)}\n\n"
                        break
            except Exception as e:
                logger.error("Streaming error: %s", str(e))
                if langfuse_enabled:
                    try:
                        get_langfuse_client().update_current_span(
                            level="ERROR",
                            status_message=str(e)[:500],
                        )
                    except Exception:
                        pass
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            finally:
                if langfuse_enabled:
                    try:
                        get_langfuse_client().flush()
                    except Exception:
                        pass

        return StreamingResponse(
            stream_generator(), media_type="text/event-stream"
        )
    except Exception as e:
        logger.error("Invocation handling error: %s", str(e))
        return {"error": str(e)}


@app.get("/ping")
async def ping():
    """
    Health check endpoint.
    """
    logger.info("Ping received.")
    return {"status": "Healthy"}
