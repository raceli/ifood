#!/bin/bash

# iFood 抓取 API Cloud Function 部署脚本
# 使用方法: ./deploy_to_cloud_function.sh [项目ID] [函数名称]

set -e

# 默认配置
DEFAULT_PROJECT_ID="aisalesagent-461308"
DEFAULT_FUNCTION_NAME="ifood-scraper"
DEFAULT_REGION="us-central1"

# 从参数或环境变量获取配置
PROJECT_ID=${1:-${GOOGLE_CLOUD_PROJECT:-$DEFAULT_PROJECT_ID}}
FUNCTION_NAME=${2:-$DEFAULT_FUNCTION_NAME}
REGION=${FUNCTION_REGION:-$DEFAULT_REGION}

echo "🚀 开始部署 iFood 抓取 API 到 Cloud Function"
echo "项目ID: $PROJECT_ID"
echo "函数名称: $FUNCTION_NAME"
echo "区域: $REGION"

# 检查必要的工具
if ! command -v gcloud &> /dev/null; then
    echo "❌ 错误: 未找到 gcloud CLI。请先安装 Google Cloud SDK"
    exit 1
fi

# 检查是否已登录
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo "❌ 错误: 未登录到 Google Cloud。请运行 'gcloud auth login'"
    exit 1
fi

# 设置项目
echo "📋 设置 GCP 项目..."
gcloud config set project $PROJECT_ID

# 启用必要的 API
echo "🔧 启用必要的 API..."
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable cloudbuild.googleapis.com

# 创建环境变量文件（如果不存在）
if [ ! -f "cloud_function_deploy.yaml" ]; then
    echo "📝 创建环境变量配置文件..."
    cat > cloud_function_deploy.yaml << EOF
API_TOKEN: "your-super-secret-token-here"
USE_GCP_NATURAL_IP_ROTATION: "true"
FUNCTION_REGION: "$REGION"
LOG_LEVEL: "INFO"
EOF
    echo "⚠️  请编辑 cloud_function_deploy.yaml 文件，设置您的 API_TOKEN"
    exit 1
fi

# 检查 API_TOKEN 是否已设置
if grep -q "your-super-secret-token-here" cloud_function_deploy.yaml; then
    echo "❌ 错误: 请在 cloud_function_deploy.yaml 中设置您的 API_TOKEN"
    exit 1
fi

# 部署 Cloud Function
echo "🚀 部署 Cloud Function..."
gcloud functions deploy $FUNCTION_NAME \
    --runtime python39 \
    --trigger-http \
    --allow-unauthenticated \
    --memory 2GB \
    --timeout 540s \
    --max-instances 10 \
    --region $REGION \
    --set-env-vars-file cloud_function_deploy.yaml \
    --source . \
    --entry-point get_menu_endpoint

echo "✅ 部署完成！"

# 获取函数URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --region=$REGION --format="value(httpsTrigger.url)")

echo "🌐 函数URL: $FUNCTION_URL"
echo ""
echo "📋 测试命令:"
echo "curl -X POST \"$FUNCTION_URL\" \\"
echo "  -H \"Authorization: Bearer your-token\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"url\": \"https://www.ifood.com.br/restaurante/example\"}'"
echo ""
echo "📊 查看日志:"
echo "gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=50"
echo ""
echo "🔧 更新函数:"
echo "gcloud functions deploy $FUNCTION_NAME --region=$REGION --source ." 