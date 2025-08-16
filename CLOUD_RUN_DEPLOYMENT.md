# Cloud Run 部署指南

## 概述

本指南将帮助您将 iFood 抓取 API 部署到 Google Cloud Run。Cloud Run 是一个完全托管的无服务器平台，非常适合运行容器化的应用程序。

## 优势

相比 Cloud Functions，Cloud Run 具有以下优势：

1. **更长的执行时间**: 支持最长 60 分钟的执行时间（可配置）
2. **更好的资源控制**: 精确控制 CPU 和内存分配
3. **原生容器支持**: 直接使用 Dockerfile 部署
4. **更好的并发处理**: 支持并发请求处理
5. **更灵活的配置**: 支持环境变量、密钥管理等

## 前置要求

1. **Google Cloud 账户**
2. **Google Cloud CLI (gcloud)**
3. **Docker** (可选，用于本地测试)
4. **jq** (用于 JSON 处理)

## 部署步骤

### 1. 安装和配置 Google Cloud CLI

```bash
# 安装 gcloud CLI
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# 登录到 Google Cloud
gcloud auth login

# 设置项目 ID
gcloud config set project YOUR_PROJECT_ID
```

### 2. 启用必要的 API

```bash
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com
```

### 3. 修改部署脚本

编辑 `deploy_to_cloud_run.sh` 文件，将 `PROJECT_ID` 替换为您的 GCP 项目 ID：

```bash
PROJECT_ID="your-actual-project-id"
```

### 4. 执行部署

```bash
# 给脚本执行权限
chmod +x deploy_to_cloud_run.sh

# 执行部署
./deploy_to_cloud_run.sh
```

## 配置说明

### 资源配置

- **内存**: 4GB (推荐用于 Playwright)
- **CPU**: 2 核
- **超时**: 900 秒 (15 分钟)
- **最大实例数**: 10
- **最小实例数**: 0 (冷启动)
- **并发数**: 1 (每个实例处理一个请求)

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `API_TOKEN` | API 认证令牌 | 必需 |
| `USE_GCP_NATURAL_IP_ROTATION` | 使用 GCP 自然 IP 轮换 | true |
| `LOG_LEVEL` | 日志级别 | INFO |

## 测试部署

### 1. 健康检查

```bash
curl https://your-service-url/health
```

### 2. API 文档

访问 `https://your-service-url/docs` 查看 Swagger UI 文档。

### 3. 测试 API

```bash
# 获取菜单
curl -X POST "https://your-service-url/get_menu" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.ifood.com.br/delivery/sao-paulo-sp/restaurante-exemplo"}'
```

## 监控和日志

### 查看日志

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=ifood-scraper" --limit=50
```

### 监控指标

在 Google Cloud Console 中查看：
- 请求数量
- 响应时间
- 错误率
- 资源使用情况

## 成本优化

### 1. 调整资源配置

根据实际使用情况调整：
- 内存和 CPU 分配
- 最大实例数
- 超时时间

### 2. 使用最小实例数

设置 `--min-instances=1` 可以避免冷启动，但会增加成本。

### 3. 优化并发设置

根据应用性能调整 `--concurrency` 参数。

## 故障排除

### 常见问题

1. **冷启动慢**
   - 考虑设置最小实例数
   - 优化 Docker 镜像大小

2. **内存不足**
   - 增加内存分配
   - 检查 Playwright 浏览器内存使用

3. **超时错误**
   - 增加超时时间
   - 优化抓取逻辑

4. **网络问题**
   - 检查防火墙规则
   - 验证代理配置

### 调试命令

```bash
# 查看服务状态
gcloud run services describe ifood-scraper --region=us-central1

# 查看最新日志
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=ifood-scraper" --limit=10

# 测试本地构建
docker build -t ifood-scraper .
docker run -p 8080:8080 ifood-scraper
```

## 安全考虑

1. **API 令牌**: 使用强密码并定期轮换
2. **网络访问**: 考虑使用 VPC 连接器
3. **环境变量**: 使用 Secret Manager 存储敏感信息
4. **HTTPS**: Cloud Run 自动提供 HTTPS

## 扩展部署

### 多区域部署

```bash
# 部署到多个区域
for region in us-central1 us-east1 europe-west1; do
  gcloud run deploy ifood-scraper-${region} \
    --image gcr.io/YOUR_PROJECT_ID/ifood-scraper \
    --region ${region} \
    --allow-unauthenticated
done
```

### 使用负载均衡器

```bash
# 创建负载均衡器
gcloud compute backend-services create ifood-backend \
  --global \
  --load-balancing-scheme=EXTERNAL_MANAGED

# 添加后端
gcloud compute backend-services add-backend ifood-backend \
  --global \
  --address=YOUR_CLOUD_RUN_IP
```

## 更新部署

```bash
# 重新构建和部署
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/ifood-scraper
gcloud run deploy ifood-scraper --image gcr.io/YOUR_PROJECT_ID/ifood-scraper --region=us-central1
```

## 删除服务

```bash
gcloud run services delete ifood-scraper --region=us-central1
``` 