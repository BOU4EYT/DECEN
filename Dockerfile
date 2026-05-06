FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DECEN_HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

COPY DECEN/requirements.txt DECEN/requirements.txt
RUN python -m pip install --no-cache-dir -r DECEN/requirements.txt

COPY DECEN DECEN
RUN mkdir -p /data

EXPOSE 8080
CMD ["python", "DECEN/server.py", "--data-dir", "/data"]
