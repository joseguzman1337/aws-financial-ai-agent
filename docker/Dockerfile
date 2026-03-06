FROM python:3.13-slim

WORKDIR /app

# Upgrade pip and install dependencies
COPY docker/requirements.txt .
RUN pip install --no-cache-dir pip==26.0.1 && \
    pip install --no-cache-dir -r requirements.txt

# Create non-root user and ensure directory ownership
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Copy application code from python directory with correct ownership
COPY --chown=appuser:appuser python/agent.py python/main.py python/tools.py ./

# Expose port 8080
EXPOSE 8080

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--log-level", "info", "--timeout-keep-alive", "120"]
