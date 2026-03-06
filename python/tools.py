"""Custom tools for stock data, sentiment, and KB/analyst report retrieval."""

import io
import os
from functools import lru_cache
from typing import List

import boto3
import requests
import yfinance as yf
from langchain_core.tools import tool
from pypdf import PdfReader


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
def retrieve_news_sentiment(symbol: str) -> str:
    """Fetches recent news and scores sentiment with FinBERT when available."""
    ticker = yf.Ticker(symbol.upper())
    news_items = ticker.news
    if not news_items:
        return f"No recent news found for {symbol}."

    headlines = []
    for item in news_items[:10]:
        # yfinance >=0.2 nests title under content{}; older versions expose it directly
        content = item.get("content", {})
        title = (
            content.get("title", item.get("title", ""))
            if content
            else item.get("title", "")
        )
        if not title:
            continue
        headlines.append(title)

    total = len(headlines)
    if total == 0:
        return f"No news headlines found for {symbol}."

    predictions = _predict_sentiment(headlines)
    pos_count = predictions.count("positive")
    neg_count = predictions.count("negative")
    neu_count = predictions.count("neutral")

    if pos_count > neg_count:
        overall = "BULLISH"
    elif neg_count > pos_count:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    mode = "FinBERT" if _finbert_available() else "keyword-fallback"
    summary = (
        f"News sentiment for {symbol}: {overall} "
        f"({pos_count}/{total} positive, {neg_count}/{total} negative, "
        f"{neu_count}/{total} neutral) using {mode}\n\n"
        "Recent Headlines:\n"
    )
    summary += "\n".join(f"- {h}" for h in headlines)
    return summary


@tool
def retrieve_knowledge_base_docs(query: str) -> str:
    """
    Queries the Bedrock Knowledge Base for Amazon financial documents.
    Use this for questions about earnings, office space, or AI business.
    """
    kb_id = os.environ.get("KNOWLEDGE_BASE_ID", "DUMMY_KB_ID")
    if kb_id == "DUMMY_KB_ID":
        return "Knowledge Base is not configured yet. Skipping retrieval."

    client = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    try:
        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": 5}
            },
        )
        results = [r["content"]["text"] for r in response.get("results", [])]
        if not results:
            return "No relevant documents found in the Knowledge Base."
        return "\n---\n".join(results)
    except Exception as error:
        return f"Warning: KB retrieval failed: {str(error)}"


@tool
def scrape_analyst_pdf_report(pdf_url: str, max_chars: int = 4000) -> str:
    """
    Downloads and extracts text from an analyst PDF report URL.
    Use this when the user provides a direct PDF link to an analyst report.
    """
    if not pdf_url.lower().startswith(("http://", "https://")):
        return "Please provide a valid HTTP/HTTPS URL for a PDF report."

    try:
        response = requests.get(pdf_url, timeout=30)
        response.raise_for_status()
    except Exception as error:
        return f"Failed to download PDF: {str(error)}"

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not pdf_url.lower().endswith(".pdf"):
        return "URL does not appear to be a PDF. Provide a direct .pdf link."

    try:
        reader = PdfReader(io.BytesIO(response.content))
        extracted: List[str] = []
        for page in reader.pages[:10]:
            text = page.extract_text() or ""
            if text.strip():
                extracted.append(text.strip())
        if not extracted:
            return "PDF downloaded, but no extractable text was found."
        joined = "\n\n".join(extracted)
        return joined[:max_chars]
    except Exception as error:
        return f"Failed to parse PDF: {str(error)}"


def _finbert_available() -> bool:
    """Returns True if transformers/torch FinBERT stack is importable."""
    try:
        import torch  # noqa: F401
        from transformers import pipeline  # noqa: F401

        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _get_finbert_pipeline():
    """Lazily creates a FinBERT sentiment pipeline once per process."""
    from transformers import pipeline

    return pipeline(
        "text-classification",
        model="ProsusAI/finbert",
        tokenizer="ProsusAI/finbert",
        truncation=True,
    )


def _predict_sentiment(headlines: List[str]) -> List[str]:
    """Predicts sentiment labels for headlines with FinBERT + fallback."""
    if _finbert_available():
        try:
            classifier = _get_finbert_pipeline()
            outputs = classifier(headlines)
            return [
                str(item.get("label", "neutral")).lower() for item in outputs
            ]
        except Exception:
            pass

    positive_words = {
        "surge",
        "gain",
        "rise",
        "beat",
        "profit",
        "growth",
        "strong",
        "bullish",
        "record",
        "upgrade",
        "positive",
        "rally",
        "outperform",
    }
    negative_words = {
        "fall",
        "drop",
        "decline",
        "loss",
        "miss",
        "weak",
        "bearish",
        "crash",
        "cut",
        "downgrade",
        "negative",
        "concern",
        "risk",
        "warn",
    }

    predictions: List[str] = []
    for title in headlines:
        words = set(title.lower().split())
        if words & positive_words:
            predictions.append("positive")
        elif words & negative_words:
            predictions.append("negative")
        else:
            predictions.append("neutral")
    return predictions
