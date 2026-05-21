FROM python:3.11-slim

# No OS-level dependencies needed for the equirectangular path.
# (Contrast with the tiling branch, which needs hugin-tools.)

WORKDIR /app

# Install Python deps first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application.
COPY . .

# Render (and most PaaS hosts) inject PORT; default to 10000 for local runs.
ENV PORT=10000
EXPOSE 10000

CMD uvicorn main:app --host 0.0.0.0 --port $PORT
