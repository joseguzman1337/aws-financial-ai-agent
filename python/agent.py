"""
This module configures the ReAct agent using LangGraph and AWS Bedrock.
Agent initialization is deferred until first invocation so the /ping health
check responds immediately (prevents Bedrock AgentCore 424 startup errors).
"""

from langchain_aws import ChatBedrockConverse
from langgraph.prebuilt import create_react_agent
from tools import (
    retrieve_historical_stock_price,
    retrieve_knowledge_base_docs,
    retrieve_news_sentiment,
    retrieve_realtime_stock_price,
)

_agent_graph = None


def get_agent_graph():
    """Returns the ReAct agent graph, initializing it on first call."""
    global _agent_graph
    if _agent_graph is None:
        model = ChatBedrockConverse(
            model="us.anthropic.claude-opus-4-6-v1",
            temperature=0,
            region_name="us-east-1",
        )
        tools = [
            retrieve_realtime_stock_price,
            retrieve_historical_stock_price,
            retrieve_news_sentiment,
            retrieve_knowledge_base_docs,
        ]
        _agent_graph = create_react_agent(model, tools=tools)
    return _agent_graph
