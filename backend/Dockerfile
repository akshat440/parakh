# Parakh backend -- FastAPI + Tesseract OCR
# Build & run:
#   docker build -t parakh-backend .
#   docker run -p 8000:8000 -e LM_SECRET_KEY=change-me parakh-backend
#
# On Render/Railway/Fly.io: point the service at this Dockerfile with the
# repo's backend/ folder as the build context.

FROM python:3.11-slim

# Tesseract is a system binary, not a Python package -- pytesseract just
# shells out to it, so it MUST be installed via apt, not pip.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Seed demo data + users on first boot if the DB doesn't exist yet.
# (On free tiers without a persistent disk, this also means the DB resets
# on every redeploy -- fine for a demo, see DEPLOY.md if you need it to persist.)
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
