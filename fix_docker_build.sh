#!/bin/bash

# Docker构建问题修复脚本
# 解决新版本Debian中包名过时的问题

set -e

echo "🔧 修复Docker构建问题..."

# 备份原始Dockerfile
if [[ -f "Dockerfile" ]]; then
    cp Dockerfile Dockerfile.backup
    echo "✅ 已备份原始Dockerfile为 Dockerfile.backup"
fi

# 使用兼容性更好的Dockerfile
if [[ -f "Dockerfile.compatible" ]]; then
    cp Dockerfile.compatible Dockerfile
    echo "✅ 已使用兼容性Dockerfile"
else
    echo "❌ 未找到Dockerfile.compatible文件"
    exit 1
fi

echo ""
echo "🎯 修复内容:"
echo "  ✅ 更新了过时的包名 (libgdk-pixbuf2.0-0 → libgdk-pixbuf-xlib-2.0-0)"
echo "  ✅ 添加了字体支持 (fonts-liberation, fonts-noto-color-emoji)"
echo "  ✅ 添加了虚拟显示支持 (xvfb)"
echo "  ✅ 改进了Playwright安装 (--with-deps)"
echo "  ✅ 添加了启动脚本处理虚拟显示"
echo ""

echo "🚀 现在可以重新构建Docker镜像:"
echo "  docker build -t ifood-scraper ."
echo ""

echo "🔄 如果需要恢复原始Dockerfile:"
echo "  cp Dockerfile.backup Dockerfile"
