"""
This module serves the FastAPI application for the Financial AI Agent.
"""

print("--- CONTAINER STARTING ---")
import json
import logging
import sys
import uuid

from agent import get_agent_graph
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
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


@app.post("/invocations")
async def invoke_agent(request: Request):
    """
    Handle POST requests for agent invocations, supporting streaming.
    """
    session_id = request.headers.get(
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", str(uuid.uuid4())
    )
    logger.info("Invocation received. Session ID: %s", session_id)

    try:
        payload = await request.json()
        query = payload.get("prompt")
        logger.info("Query: %s", query)

        langfuse_handler = CallbackHandler(
            trace_context={"trace_id": session_id}
        )

        agent_input = {"messages": [("user", query)]}
        config = {
            "callbacks": [langfuse_handler],
            "metadata": {"langfuse_session_id": session_id},
            "recursion_limit": 25,
        }

        async def stream_generator():
            try:
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
