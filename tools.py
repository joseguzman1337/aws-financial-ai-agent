"""
This module provides custom tools for the AI agent to fetch stock data.
"""

import boto3
import yfinance as yf
from langchain_core.tools import tool


@tool
def retrieve_realtime_stock_price(symbol: str) -> str:
    """Fetches the real-time stock price and day's range."""
    ticker = yf.Ticker(symbol.upper())
    price = ticker.info.get("regularMarketPrice", "N/A")
    return f"Real-time price for {symbol}: ${price}"


@tool
def retrieve_historical_stock_price(
    symbol: str, period: str, interval: str = "1d"
) -> str:
    """Queries historical OHLC data for specific periods."""
    ticker = yf.Ticker(symbol.upper())
    history = ticker.history(period=period, interval=interval)
    return history.to_string()


@tool
def retrieve_knowledge_base_docs(query: str) -> str:
    """
    Queries the Bedrock Knowledge Base for Amazon financial documents.
    Use this for questions about earnings, office space, or AI business.
    """
    client = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    # In a real scenario, the KB ID would be an environment variable or
    # passed via config.
    # We'll use a placeholder or assume it's provisioned.
    # Note: For the sake of this demo, we assume the KB is already provisioned
    # and has an ID.
    kb_id = "AMAZON_FINANCIAL_DOCS_KB_ID"

    try:
        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": 5}
            },
        )
        results = [r["content"]["text"] for r in response.get("results", [])]
        return "\n---\n".join(results)
    except Exception as error:
        return f"Error retrieving documents: {str(error)}"
