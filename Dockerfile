FROM python:3.11-slim

# Set working dir inside tax_agent subdir
WORKDIR /app/tax_agent

# Install deps first (layer caching)
COPY tax_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy full backend
COPY . /app

# Cloud Run injects PORT env var — uvicorn picks it up via settings.port
ENV PORT=8080

CMD ["python", "main.py"]
