#!/bin/bash

# Cloud Run 部署脚本
# 用于部署 iFood 抓取 API 到 Google Cloud Run

set -e

# 配置变量
PROJECT_ID="your-gcp-project-id"  # 请替换为您的GCP项目ID
SERVICE_NAME="ifood-scraper"
REGION="us-central1"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}开始部署到 Cloud Run...${NC}"

# 1. 设置项目
echo -e "${YELLOW}设置GCP项目...${NC}"
gcloud config set project ${PROJECT_ID}

# 2. 启用必要的API
echo -e "${YELLOW}启用必要的GCP API...${NC}"
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com

# 3. 构建并推送Docker镜像
echo -e "${YELLOW}构建Docker镜像...${NC}"
gcloud builds submit --tag ${IMAGE_NAME}

# 4. 部署到Cloud Run
echo -e "${YELLOW}部署到Cloud Run...${NC}"
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 2 \
  --timeout 900 \
  --max-instances 10 \
  --min-instances 0 \
  --concurrency 1 \
  --set-env-vars="API_TOKEN=4a27e60b5b0464a72ae12ba3731e077cc5951b40937999e78d06fb5325524800" \
  --set-env-vars="USE_GCP_NATURAL_IP_ROTATION=true" \
  --set-env-vars="LOG_LEVEL=INFO"

# 5. 获取服务URL
echo -e "${YELLOW}获取服务URL...${NC}"
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")

echo -e "${GREEN}部署完成！${NC}"
echo -e "${GREEN}服务URL: ${SERVICE_URL}${NC}"
echo -e "${GREEN}健康检查: ${SERVICE_URL}/health${NC}"
echo -e "${GREEN}API文档: ${SERVICE_URL}/docs${NC}"

# 6. 测试健康检查
echo -e "${YELLOW}测试健康检查...${NC}"
curl -s ${SERVICE_URL}/health | jq . || echo "健康检查失败，请检查服务状态"

echo -e "${GREEN}部署脚本执行完成！${NC}" 