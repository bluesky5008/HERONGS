# HERONGS — 단일 컨테이너: FastAPI + 스케줄러 + WebSocket + PWA 정적 서빙 (설계 §11.2)

# 1단계: PWA 빌드
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# 2단계: 백엔드 (설계 스택: Python 3.12)
FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/herongs ./herongs
RUN pip install --no-cache-dir .
COPY --from=frontend /build/dist ./static

# 스케줄러(장전 08:30/마감 15:40/백업 03:00)와 장 운영시간 판정은 KST 기준 (NFR-04)
ENV TZ=Asia/Seoul
ENV HERONGS_DB_PATH=/app/data/herongs.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["python", "-m", "uvicorn", "herongs.main:app", "--host", "0.0.0.0", "--port", "8000"]
