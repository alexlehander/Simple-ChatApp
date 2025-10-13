FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Copy backend source
COPY LLM_BACKEND/LLM_BACKEND-main/ /app/

# Install dependencies
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Expose backend port
EXPOSE 8000

# Start backend directly (no wait script)
CMD ["gunicorn", "-b", "0.0.0.0:8000", "app:app"]