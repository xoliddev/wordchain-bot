FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# Run without root; the data volume is owned by this user (a new named volume inherits it)
RUN useradd --create-home --uid 10001 wordchain && mkdir -p /app/data && chown wordchain /app/data
USER wordchain

VOLUME /app/data
CMD ["python", "-m", "bot"]
