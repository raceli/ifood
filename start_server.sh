#!/bin/bash

# iFood Menu API 启动脚本

echo "🚀 启动 iFood Menu API 服务器..."
echo "=================================="

# 检查 Python 版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "🐍 Python 版本: $python_version"

# 检查依赖是否安装
echo "📦 检查依赖..."
if ! python3 -c "import fastapi, playwright, uvicorn" 2>/dev/null; then
    echo "❌ 缺少依赖，正在安装..."
    pip3 install -r requirements.txt
fi

# 检查 Playwright 浏览器
echo "🌐 检查 Playwright 浏览器..."
if ! playwright --version >/dev/null 2>&1; then
    echo "❌ Playwright 未安装，正在安装..."
    playwright install
fi

# 检查代理文件
if [ -f "proxies.txt" ]; then
    echo "✅ 找到代理文件: proxies.txt"
    proxy_count=$(grep -v '^#' proxies.txt | grep -v '^$' | wc -l)
    echo "📊 可用代理数量: $proxy_count"
else
    echo "⚠️  未找到代理文件 proxies.txt，将使用直接连接"
fi

# 检查环境变量
echo "🔧 环境配置:"
echo "   API_TOKEN: ${API_TOKEN:-未设置 (使用默认值)}"
echo "   代理策略: ${PROXY_ROTATION_STRATEGY:-random}"
echo "   Cloud Function: ${FUNCTION_TARGET:-否}"

# 启动服务器
echo ""
echo "🎯 启动服务器..."
echo "📍 服务器地址: http://0.0.0.0:8000"
echo "📚 API 文档: http://0.0.0.0:8000/docs"
echo "🔑 认证令牌: ${API_TOKEN:-local-dev-token}"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "=================================="

# 启动 FastAPI 服务器
python3 api.py 