FROM python:3.11-slim

WORKDIR /app

# Upgrade pip and install dependencies
COPY docker/requirements.txt .
RUN pip install --no-cache-dir pip==26.0.1 && \
    pip install --no-cache-dir -r requirements.txt

# Create non-root user and ensure directory ownership
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Copy application code with correct ownership
COPY --chown=appuser:appuser python/agent.py python/main.py python/tools.py ./

# Expose port 8080
EXPOSE 8080

# Healthcheck with increased grace period for cold starts
HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=5 \
  CMD python3 -c "import urllib.request; import sys; try: urllib.request.urlopen('http://localhost:8080/ping', timeout=10); sys.exit(0); except Exception: sys.exit(1)"

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
