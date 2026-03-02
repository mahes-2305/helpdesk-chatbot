# Use Python 3.11 (required for numpy 2.x)
FROM python:3.11

# Prevent Python from buffering logs
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies (needed for numpy/scipy)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better Docker caching)
COPY requirements.txt .

# Upgrade pip
RUN pip install --upgrade pip

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of project files
COPY . .

# HuggingFace Spaces uses port 7860
EXPOSE 7860

# Run your Flask app
CMD ["python", "app.py"]