FROM python:3.13-slim

WORKDIR /app

# Upgrade pip and install dependencies
# We assume the build context is the repository root
COPY docker/requirements.txt .
RUN pip install --no-cache-dir pip==26.0.1 && \
    pip install --no-cache-dir -r requirements.txt

# Create and switch to a non-root user
RUN useradd -m appuser
USER appuser

# Copy application code from python directory
COPY python/agent.py python/main.py python/tools.py .

# Expose port 8080
EXPOSE 8080

# Healthcheck to signal container readiness
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; import sys; try: urllib.request.urlopen('http://localhost:8080/ping', timeout=10); sys.exit(0); except Exception: sys.exit(1)"

# Run the application
# We copied the files directly into /app, so we run main:app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
