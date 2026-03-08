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
from langfuse import get_client, propagate_attributes
from langfuse_config import ensure_langfuse_env
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


@app.on_event("shutdown")
async def flush_langfuse():
    """Flush Langfuse events on graceful shutdown."""
    if ensure_langfuse_env():
        try:
            get_client().flush()
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
                        trace_id = get_client().create_trace_id(
                            seed=external_trace_seed
                        )
                        trace_context = {"trace_id": trace_id}
                    except Exception:
                        trace_context = {}
            langfuse_handler = CallbackHandler(
                trace_context=trace_context,
                environment=tracing_environment,
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
                "agent_runtime": "Financial_Analyst_Agent",
                "has_prompt": bool(query),
            },
            "recursion_limit": 25,
        }

        async def stream_generator():
            try:
                langfuse = get_client() if langfuse_enabled else None
                if langfuse:
                    with langfuse.start_as_current_observation(
                        as_type="span",
                        name="agentcore-invocation",
                        trace_context=trace_context,
                        input={
                            "session_id": session_id,
                            "user_id": user_id,
                            "environment": tracing_environment,
                            "trace_seed": external_trace_seed,
                            "tags": langfuse_tags,
                            "metadata": langfuse_metadata,
                            "prompt": query,
                        },
                    ) as span:
                        with propagate_attributes(
                            session_id=session_id,
                            user_id=user_id,
                            environment=tracing_environment,
                            tags=langfuse_tags,
                            metadata=langfuse_metadata,
                        ):
                            result = await get_agent_graph().ainvoke(
                                agent_input, config=config
                            )
                        span.update(output={"status": "ok"})
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
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
