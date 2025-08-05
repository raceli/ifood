# 1. 使用官方的Python 3.11 slim版本作为基础镜像
FROM python:3.11-slim

# 设置一个环境变量，避免在安装时出现不必要的交互提示
ENV DEBIAN_FRONTEND=noninteractive

# 2. 安装Playwright运行所需的系统级依赖
#    - 更新apt包列表
#    - 安装wget和xvfb等核心工具
#    - 清理apt缓存以减小镜像体积
RUN apt-get update && \
    apt-get install -y wget xvfb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 3. 在容器内创建并设置工作目录
WORKDIR /app

# 4. 复制依赖和代理配置文件到容器中
COPY requirements.txt proxies.txt /app/

# 5. 安装Python依赖
#    --no-cache-dir 选项可以减小镜像层的大小
RUN pip install --no-cache-dir -r requirements.txt

# 6. 安装Playwright的浏览器核心 (只安装chromium以减小体积)
#    --with-deps 会一并安装所需的操作系统依赖
RUN playwright install --with-deps chromium

# 7. 复制API应用代码到容器中
COPY api.py /app/

# 8. 暴露API服务将要监听的端口
EXPOSE 8000

# 9. 设置容器启动时执行的命令
#    --host 0.0.0.0 让服务可以从容器外部访问
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"] 