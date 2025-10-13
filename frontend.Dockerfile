FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy frontend source
COPY LLM_FRONTEND/LLM_FRONTEND-main/ /app/

# Install dependencies
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose frontend port
EXPOSE 3000

# Run the Flet app
CMD ["python", "app_chat.py"]