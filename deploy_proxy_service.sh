#!/bin/bash

# iFood 代理服务 Cloud Function 部署脚本
# 使用方法: ./deploy_proxy_service.sh [项目ID] [函数名称]

set -e

# 默认配置
DEFAULT_PROJECT_ID="aisalesagent-461308"
DEFAULT_FUNCTION_NAME="ifood-proxy"
DEFAULT_REGION="us-central1"

# 从参数或环境变量获取配置
PROJECT_ID=${1:-${GOOGLE_CLOUD_PROJECT:-$DEFAULT_PROJECT_ID}}
FUNCTION_NAME=${2:-$DEFAULT_FUNCTION_NAME}
REGION=${FUNCTION_REGION:-$DEFAULT_REGION}

echo "🚀 开始部署 iFood 代理服务到 Cloud Function"
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
gcloud services enable artifactregistry.googleapis.com

# 创建 Artifact Registry 仓库 (如果不存在)
echo "📦 创建 Artifact Registry 仓库..."
gcloud artifacts repositories create ${FUNCTION_NAME} \
    --repository-format=docker \
    --location=$REGION \
    --description="Docker repository for ${FUNCTION_NAME} Proxy Service" \
    --quiet || echo "仓库已存在，跳过创建"

# 安装 Playwright 浏览器
echo "🔧 安装 Playwright 浏览器..."
./install_playwright.sh

# 构建 Docker 镜像 (使用 Artifact Registry 格式)
echo "🔧 构建 Docker 镜像..."
docker build -t ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}/proxy-image .

# 推送镜像到 Artifact Registry
echo "📤 推送镜像到 Artifact Registry..."
docker push ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}/proxy-image

# 部署代理端点函数
echo "🚀 部署代理端点函数..."
gcloud functions deploy ${FUNCTION_NAME}-proxy \
    --gen2 \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated \
    --memory 4GB \
    --timeout 600s \
    --max-instances 10 \
    --min-instances 0 \
    --concurrency 1 \
    --cpu 2 \
    --region $REGION \
    --env-vars-file cloud_function_deploy.yaml \
    --source . \
    --entry-point proxy_endpoint_sync \
    --docker-registry artifact-registry \
    --docker-repository ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}

# 部署简单代理端点函数
echo "🚀 部署简单代理端点函数..."
gcloud functions deploy ${FUNCTION_NAME}-simple \
    --gen2 \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated \
    --memory 4GB \
    --timeout 600s \
    --max-instances 10 \
    --min-instances 0 \
    --concurrency 1 \
    --cpu 2 \
    --region $REGION \
    --env-vars-file cloud_function_deploy.yaml \
    --source . \
    --entry-point simple_proxy_endpoint_sync \
    --docker-registry artifact-registry \
    --docker-repository ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}

# 部署健康检查端点函数
echo "🚀 部署健康检查端点函数..."
gcloud functions deploy ${FUNCTION_NAME}-health \
    --gen2 \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated \
    --memory 1GB \
    --timeout 60s \
    --max-instances 10 \
    --min-instances 0 \
    --concurrency 1 \
    --cpu 1 \
    --region $REGION \
    --env-vars-file cloud_function_deploy.yaml \
    --source . \
    --entry-point health_check_sync \
    --docker-registry artifact-registry \
    --docker-repository ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}

# 部署测试端点函数
echo "🚀 部署测试端点函数..."
gcloud functions deploy ${FUNCTION_NAME}-test \
    --gen2 \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated \
    --memory 4GB \
    --timeout 600s \
    --max-instances 10 \
    --min-instances 0 \
    --concurrency 1 \
    --cpu 2 \
    --region $REGION \
    --env-vars-file cloud_function_deploy.yaml \
    --source . \
    --entry-point test_endpoint_sync \
    --docker-registry artifact-registry \
    --docker-repository ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}

echo "✅ 代理服务部署完成！"

# 获取函数URL
PROXY_FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME}-proxy --region=$REGION --format="value(httpsTrigger.url)")
SIMPLE_FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME}-simple --region=$REGION --format="value(httpsTrigger.url)")
HEALTH_FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME}-health --region=$REGION --format="value(httpsTrigger.url)")
TEST_FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME}-test --region=$REGION --format="value(httpsTrigger.url)")

echo "🌐 代理端点URL: $PROXY_FUNCTION_URL"
echo "🌐 简单代理端点URL: $SIMPLE_FUNCTION_URL"
echo "🌐 健康检查端点URL: $HEALTH_FUNCTION_URL"
echo "🌐 测试端点URL: $TEST_FUNCTION_URL"

echo ""
echo "📋 使用示例:"
echo ""
echo "# 健康检查"
echo "curl -X GET \"$HEALTH_FUNCTION_URL\""
echo ""
echo "# 测试代理服务"
echo "curl -X GET \"$TEST_FUNCTION_URL\""
echo ""
echo "# 简单代理请求"
echo "curl -X POST \"$SIMPLE_FUNCTION_URL\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"url\": \"https://www.ifood.com.br\"}'"
echo ""
echo "# 完整代理请求"
echo "curl -X POST \"$PROXY_FUNCTION_URL\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{"
echo "    \"url\": \"https://www.ifood.com.br\","
echo "    \"method\": \"GET\","
echo "    \"timeout\": 30,"
echo "    \"extract_text\": true,"
echo "    \"screenshot\": false"
echo "  }'"
echo ""
echo "🎯 现在您的 K8s 服务可以通过这些端点访问 iFood 网页了！" 