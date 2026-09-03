# Single-stage, matching backend/Dockerfile's shape (pure Python, no build
# step) rather than frontend/Dockerfile's multi-stage Node build. Build
# context is ./mcp itself (docker-compose.yml's `mcp` service), not the
# repo root — unlike frontend, this service bakes in nothing from outside
# its own directory (see docker-compose.yml's `mcp` build block for why).
FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY afp_client.py server.py ./

EXPOSE 8000
CMD ["python", "server.py"]
