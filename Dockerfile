FROM python:3.11-slim

# Render doesn't allow 'sudo apt-get' natively on standard Python environments.
# To install 'nona' (which is packaged inside 'hugin-tools'), we must use Docker!
RUN apt-get update && apt-get install -y \
    hugin-tools \
    libpano13-bin \
    && rm -rf /var/lib/apt/lists/*

# Set up our application directory
WORKDIR /app

# Copy Requirements and Install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files (main.py, processor.py, uploader.py, scripts/, etc)
COPY . .

# Render dynamically sets the 'PORT' environment variable, defaulting to 10000.
# We expose it to route traffic properly.
ENV PORT=10000
EXPOSE 10000

# The command that starts the server
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
