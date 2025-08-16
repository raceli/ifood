# 使用 Python 3.11 作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖 (Playwright 所需)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    procps \
    libxss1 \
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libgdk-pixbuf2.0-0 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright 浏览器
RUN playwright install chromium

# 验证浏览器安装
RUN playwright --version

# 复制应用代码
COPY . .

# 设置环境变量
ENV PYTHONPATH=/app
ENV PORT=8080
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# 暴露端口
EXPOSE 8080

# 启动命令 - 使用uvicorn启动FastAPI应用
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"] 