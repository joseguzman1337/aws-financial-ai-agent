"""
This module configures the ReAct agent using LangGraph and OpenAI.
"""

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from tools import (
    retrieve_historical_stock_price,
    retrieve_realtime_stock_price,
)

# Use a smaller/freer model for testing if possible.
# Using gpt-4o-mini to reduce costs for tests.
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
tools = [retrieve_realtime_stock_price, retrieve_historical_stock_price]

# ReAct framework orchestrates the Reason + Act loop
agent_graph = create_react_agent(model, tools=tools)
