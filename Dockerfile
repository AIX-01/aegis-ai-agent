# ============================================
# AEGIS AI Agent - Dockerfile
# Python 3.12 + OpenCV + FastAPI + LangGraph
# ============================================

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

WORKDIR /app

# 시스템 의존성 설치 (OpenCV 빌드용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    libglib2.0-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.12-slim

WORKDIR /app

# 런타임 의존성만 설치 (OpenCV 실행용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Builder에서 설치된 패키지 복사
COPY --from=builder /root/.local /root/.local

# PATH에 추가
ENV PATH=/root/.local/bin:$PATH

# 소스 코드 복사
COPY src/ ./src/

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 포트 노출
# 8000: Agent API Server
# 8001: Mock VLM Server (mock_mode=True)
# 8002: Mock Precision Server (mock_mode=True)
# 8088: Mock Backend Server (mock_mode=True)
EXPOSE 8000 8001 8002 8088

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 기본 실행 명령어 (Mock 모드)
# 실제 서버 연동시: CMD ["python", "-m", "src.app", "--no-mock"]
CMD ["python", "-m", "src.app"]

