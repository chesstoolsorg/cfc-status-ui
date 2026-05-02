# Build from repository root:
#   docker build -f cfc-status-ui/Dockerfile .
FROM python:3.11-slim

WORKDIR /app/cfc-status-ui

COPY shared/chesstools-ui /app/shared/chesstools-ui
COPY cfc-status-ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cfc-status-ui .

EXPOSE 8080

ENV PORT=8080

CMD ["python", "wsgi.py"]
