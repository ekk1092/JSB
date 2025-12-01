# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (needed for some python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose ports (Streamlit uses 8501 by default)
EXPOSE 8501

# Define environment variables (can be overridden at runtime)
# ENV AZURE_OPENAI_API_KEY=...

# Default command (can be overridden)
CMD ["python", "server/main.py"]
