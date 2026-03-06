"""
This module serves the FastAPI application for the Financial AI Agent.
"""

import json
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from langfuse.callback import CallbackHandler

from agent import agent_graph

app = FastAPI()


@app.post("/invocations")
async def invoke_agent(request: Request):
    """
    Handle POST requests for agent invocations, supporting streaming.
    """
    # AgentCore injects the session ID into the headers
    session_id = request.headers.get(
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", str(uuid.uuid4())
    )
    payload = await request.json()
    query = payload.get("prompt")

    # Initialize Langfuse CallbackHandler for cloud observability
    langfuse_handler = CallbackHandler(session_id=session_id)

    agent_input = {"messages": [("user", query)]}
    config = {
        "callbacks": [langfuse_handler],
        "metadata": {"langfuse_session_id": session_id},
        "recursion_limit": 25,
    }

    async def stream_generator():
        try:
            # Streams events via .astream() yielding incremental updates
            async for chunk in agent_graph.astream(
                agent_input, config=config, stream_mode="messages"
            ):
                message_chunk, _ = chunk
                if message_chunk.content:
                    # Format as Server-Sent Events (SSE)
                    chunk_data = {"event": message_chunk.content}
                    yield f"data: {json.dumps(chunk_data)}\n\n"
            langfuse_handler.flush()
        except RuntimeError as runtime_error:
            yield f"data: {json.dumps({'error': str(runtime_error)})}\n\n"
        except ValueError as value_error:
            yield f"data: {json.dumps({'error': str(value_error)})}\n\n"

    # text/event-stream allows clients to parse incoming data progressively
    return StreamingResponse(
        stream_generator(), media_type="text/event-stream"
    )


@app.get("/ping")
async def ping():
    """
    Health check endpoint for the AgentCore runtime.
    """
    # Signals to Agentcore that the system is ready to accept new work
    return {"status": "Healthy"}
