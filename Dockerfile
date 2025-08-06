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
    libdrm2 \
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

# 安装 Playwright 浏览器 (参考 GitHub issue #1491)
RUN playwright install chromium

# 验证浏览器安装
RUN playwright --version && \
    find / -name "chromium-*" -type d 2>/dev/null | head -5 && \
    ls -la ~/.cache/ms-playwright/ 2>/dev/null || echo "浏览器安装在默认位置"

# 复制应用代码
COPY . .

# 设置环境变量
ENV PYTHONPATH=/app
ENV FUNCTION_TARGET=get_menu_endpoint_sync
ENV PLAYWRIGHT_BROWSERS_PATH=/www-data-home/.cache/ms-playwright

# 暴露端口
EXPOSE 8080

# 启动命令
CMD ["python", "main.py"] 