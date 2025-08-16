#!/bin/bash

# 多区域Cloud Run部署脚本
# 在不同区域部署相同服务，获得更多IP地址

set -e

PROJECT_ID="your-project-id"
SERVICE_NAME="ifood-scraper"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# GCP区域列表（选择延迟较低的区域）
REGIONS=(
    "us-central1"      # 美国中部
    "us-east1"         # 美国东部  
    "europe-west1"     # 欧洲西部
    "asia-east1"       # 亚洲东部
    "southamerica-east1" # 南美洲东部（最接近巴西）
)

echo "🚀 开始多区域部署..."

# 构建镜像
echo "📦 构建Docker镜像..."
gcloud builds submit --tag $IMAGE_NAME

# 逐个区域部署
for region in "${REGIONS[@]}"; do
    echo "🌍 部署到区域: $region"
    
    gcloud run deploy "${SERVICE_NAME}-${region}" \
        --image $IMAGE_NAME \
        --platform managed \
        --region $region \
        --allow-unauthenticated \
        --memory 4Gi \
        --cpu 2 \
        --timeout 900 \
        --max-instances 10 \
        --min-instances 0 \
        --concurrency 1 \
        --set-env-vars USE_GCP_NATURAL_IP_ROTATION=true,API_TOKEN=your-api-token \
        --quiet
    
    echo "✅ $region 部署完成"
done

echo "🎉 所有区域部署完成！"

# 输出服务URL
echo "📝 服务URL列表:"
for region in "${REGIONS[@]}"; do
    URL=$(gcloud run services describe "${SERVICE_NAME}-${region}" --region=$region --format='value(status.url)')
    echo "  $region: $URL"
done
