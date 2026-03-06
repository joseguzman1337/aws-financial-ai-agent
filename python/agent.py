"""
This module configures the ReAct agent using LangGraph and OpenAI.
"""

from langchain_aws import ChatBedrock
from langgraph.prebuilt import create_react_agent
from tools import (
    retrieve_historical_stock_price,
    retrieve_knowledge_base_docs,
    retrieve_realtime_stock_price,
)

# Using ChatBedrock to utilize AWS Bedrock models as requested by task1.txt
model = ChatBedrock(
    model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
    model_kwargs={"temperature": 0},
    region_name="us-east-1",
)

tools = [
    retrieve_realtime_stock_price,
    retrieve_historical_stock_price,
    retrieve_knowledge_base_docs,
]

# ReAct framework orchestrates the Reason + Act loop
agent_graph = create_react_agent(model, tools=tools)
