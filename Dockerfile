FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot.py database.py words.txt ./

RUN useradd -m -u 10001 botuser && mkdir -p /data && chown -R botuser:botuser /app /data

USER botuser

VOLUME ["/data"]

CMD ["python", "bot.py"]
