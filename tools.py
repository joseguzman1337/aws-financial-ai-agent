"""
This module provides custom tools for the AI agent to fetch stock data.
"""

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
