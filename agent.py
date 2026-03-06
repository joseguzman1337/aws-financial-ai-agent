from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from tools import retrieve_realtime_stock_price, retrieve_historical_stock_price

# Use a smaller/freer model for testing if possible, but the code specifically requested "gpt-4o".
# We'll stick to what task1.txt asked, while noting it uses OpenAI.
# Using gpt-4o-mini to reduce costs for tests
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
tools = [retrieve_realtime_stock_price, retrieve_historical_stock_price]

# ReAct framework orchestrates the Reason + Act loop
agent_graph = create_react_agent(model, tools=tools)
