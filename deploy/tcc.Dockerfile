# Build only from the sanitized release directory produced by prepare_tcc_release.
FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
ENV VITE_API_URL=/sigra-api VITE_PUBLIC_DEMO_MODE=false VITE_ACADEMIC_TEST_MODE=false
RUN npm run build

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && useradd --uid 10001 --create-home sigra
COPY backend/ ./backend/
COPY data_platform/ ./data_platform/
COPY release/ ./release/
COPY deploy/ ./deploy/
COPY scripts/ ./scripts/
COPY docs/ ./docs/
COPY frontend/ ./frontend/
COPY --from=frontend /build/frontend/dist ./frontend/dist/
ENV PYTHONPATH=/app/backend:/app
USER 10001:10001
EXPOSE 10000
CMD ["python", "-B", "deploy/start_tcc.py"]
