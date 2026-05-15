FROM python:3.11-slim

# Node.js 20 설치
RUN apt-get update && apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Puppeteer/Chromium 런타임 의존성
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 \
    libdbus-1-3 libexpat1 \
    libxcb1 libxkbcommon0 \
    libx11-6 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 의존성 먼저 설치 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node 의존성 설치
COPY package.json package-lock.json* ./
RUN npm install

# 소스 복사
COPY . .

CMD ["python3", "start.py"]
