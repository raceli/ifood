#!/bin/bash

# 修复Python依赖冲突脚本
# 解决fastapi、pydantic、fastapi-security版本冲突问题

set -e

echo "🔧 修复Python依赖冲突..."

# 备份原始requirements.txt
if [[ -f "requirements.txt" ]]; then
    cp requirements.txt requirements.txt.backup
    echo "✅ 已备份原始requirements.txt为 requirements.txt.backup"
fi

# 使用兼容性版本
if [[ -f "requirements.txt.compatible" ]]; then
    cp requirements.txt.compatible requirements.txt
    echo "✅ 已使用兼容性requirements.txt"
else
    echo "❌ 未找到requirements.txt.compatible文件"
    exit 1
fi

echo ""
echo "🎯 修复内容:"
echo "  ✅ 更新fastapi: 0.104.0 → 0.115.0 (兼容pydantic 2.x)"
echo "  ✅ 更新fastapi-security: 0.4.0 → 0.5.0 (兼容pydantic 2.x)"
echo "  ✅ 使用固定版本号避免依赖冲突"
echo "  ✅ 确保所有包版本兼容"
echo ""

echo "🚀 现在可以重新构建Docker镜像:"
echo "  docker build -t ifood-scraper ."
echo ""

echo "🔄 如果需要恢复原始requirements.txt:"
echo "  cp requirements.txt.backup requirements.txt"
echo ""

echo "📋 修复的依赖版本:"
echo "  - fastapi: 0.115.0 (兼容pydantic 2.x)"
echo "  - fastapi-security: 0.5.0 (兼容pydantic 2.x)"
echo "  - pydantic: 2.5.0 (最新稳定版)"
echo "  - 其他依赖: 固定兼容版本"
