FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 (mysqlclient 빌드 불필요 — pymysql 사용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && \
    rm -rf /var/lib/apt/lists/*

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt email-validator

# 소스 복사
COPY . .

# Railway는 PORT 환경변수를 자동 주입
ENV PORT=8000

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
