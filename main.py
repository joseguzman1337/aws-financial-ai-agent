import uuid
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from langfuse.callback import CallbackHandler
from agent import agent_graph

app = FastAPI()

@app.post("/invocations")
async def invoke_agent(request: Request):
    # AgentCore injects the session ID into the headers
    session_id = request.headers.get("X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", str(uuid.uuid4()))
    payload = await request.json()
    query = payload.get("prompt")

    # Initialize Langfuse CallbackHandler for cloud observability
    langfuse_handler = CallbackHandler(session_id=session_id)
    
    agent_input = {"messages": [("user", query)]}
    config = {
        "callbacks": [langfuse_handler], 
        "metadata": {"langfuse_session_id": session_id},
        "recursion_limit": 25
    }

    async def stream_generator():
        try:
            # Streams events via .astream() yielding incremental updates
            async for chunk in agent_graph.astream(agent_input, config=config, stream_mode="messages"):
                message_chunk, metadata = chunk
                if message_chunk.content:
                    # Format as Server-Sent Events (SSE)
                    yield f"data: {json.dumps({'event': message_chunk.content})}\n\n"
            langfuse_handler.flush()
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    # text/event-stream allows clients to parse incoming data progressively
    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@app.get("/ping")
async def ping():
    # Signals to Agentcore that the system is ready to accept new work
    return {"status": "Healthy"}
