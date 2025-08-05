#!/bin/bash

# 安装 Playwright 浏览器脚本
# 这个脚本需要在 Cloud Functions 部署前运行

echo "🔧 安装 Playwright 浏览器..."

# 安装 Playwright 浏览器
playwright install chromium

echo "✅ Playwright 浏览器安装完成！" 