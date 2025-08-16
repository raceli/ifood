#!/bin/bash

# 设置负载均衡器来分散请求到不同区域的Cloud Run服务
# 这样可以自动获得更多IP地址的变化

PROJECT_ID="your-project-id"
SERVICE_NAME="ifood-scraper"

echo "🔧 创建全局负载均衡器..."

# 1. 创建全局负载均衡器
gcloud compute backend-services create ${SERVICE_NAME}-backend \
    --global \
    --load-balancing-scheme=EXTERNAL_MANAGED \
    --protocol=HTTPS

# 2. 为每个区域的Cloud Run服务创建NEG (Network Endpoint Group)
REGIONS=("us-central1" "us-east1" "europe-west1" "southamerica-east1")

for region in "${REGIONS[@]}"; do
    echo "🌐 为区域 $region 创建NEG..."
    
    # 创建无服务器NEG
    gcloud compute network-endpoint-groups create ${SERVICE_NAME}-neg-${region} \
        --region=$region \
        --network-endpoint-type=serverless \
        --cloud-run-service=${SERVICE_NAME}-${region}
    
    # 将NEG添加到后端服务
    gcloud compute backend-services add-backend ${SERVICE_NAME}-backend \
        --global \
        --network-endpoint-group=${SERVICE_NAME}-neg-${region} \
        --network-endpoint-group-region=$region
done

# 3. 创建URL映射
gcloud compute url-maps create ${SERVICE_NAME}-url-map \
    --default-service=${SERVICE_NAME}-backend

# 4. 创建SSL证书（可选）
gcloud compute ssl-certificates create ${SERVICE_NAME}-ssl-cert \
    --domains=your-domain.com

# 5. 创建HTTPS代理
gcloud compute target-https-proxies create ${SERVICE_NAME}-https-proxy \
    --url-map=${SERVICE_NAME}-url-map \
    --ssl-certificates=${SERVICE_NAME}-ssl-cert

# 6. 创建全局转发规则
gcloud compute forwarding-rules create ${SERVICE_NAME}-https-rule \
    --global \
    --target-https-proxy=${SERVICE_NAME}-https-proxy \
    --ports=443

# 获取负载均衡器IP
LB_IP=$(gcloud compute forwarding-rules describe ${SERVICE_NAME}-https-rule --global --format='value(IPAddress)')

echo "🎉 负载均衡器设置完成！"
echo "📍 负载均衡器IP: $LB_IP"
echo "🌍 流量将自动分散到不同区域的服务"
