# 🚀 iFood API 快速部署指南 (无代理版本)

## 📋 部署前准备

### 1. 安装必要工具
```bash
# 安装 Google Cloud CLI
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# 登录GCP
gcloud auth login

# 设置项目ID
gcloud config set project YOUR_PROJECT_ID
```

### 2. 启用必要API
```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com containerregistry.googleapis.com
```

## 🎯 一键部署到圣保罗机房

```bash
# 1. 给脚本执行权限
chmod +x deploy_sao_paulo.sh

# 2. 修改配置 (可选)
# 编辑 deploy_sao_paulo.sh，修改 API_TOKEN 和 PROJECT_ID

# 3. 执行部署
./deploy_sao_paulo.sh
```

## 🔧 部署配置

| 配置项 | 值 | 说明 |
|-------|------|------|
| **区域** | southamerica-east1 | 圣保罗机房 (距离iFood最近) |
| **内存** | 4GB | 适合Playwright运行 |
| **CPU** | 2核 | 高性能处理 |
| **超时** | 15分钟 | 充足的处理时间 |
| **并发** | 1请求/实例 | 最大化IP轮换效果 |
| **最大实例** | 10个 | 支持突发流量 |
| **最小实例** | 0个 | 成本优化 |

## 🛡️ 防封禁策略 (无代理版本)

### ✅ 核心防护
- 🌍 **GCP自然IP轮换**: 每次冷启动自动换IP
- 🎭 **浏览器指纹伪装**: 模拟真实巴西用户
- ⏰ **人类行为模拟**: 智能请求延迟
- 🧠 **JavaScript反检测**: 绕过自动化检测

### 🚫 已禁用
- ❌ 代理功能: 专注GCP IP轮换，降低成本
- ❌ 第三方代理: 避免代理质量不稳定问题

## 🧪 验证部署

```bash
# 执行验证脚本
./test_sao_paulo_deployment.sh
```

## 📊 预期效果

- **IP变化频率**: 每次冷启动 ~80% 概率换IP
- **地理位置**: 100% 巴西本地IP
- **延迟**: 最低延迟 (圣保罗机房)
- **成本**: 无额外代理费用
- **稳定性**: 高 (GCP基础设施)

## 🔗 使用API

### 获取餐厅菜单
```bash
curl -X POST "https://your-service-url/get_shop_all" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.ifood.com.br/delivery/sao-paulo-sp/restaurant-url"
  }'
```

### 查看服务状态
```bash
curl -H "Authorization: Bearer YOUR_API_TOKEN" \
  "https://your-service-url/status"
```

## 💰 成本估算

- **Cloud Run**: ~$0.50-2.00/天 (取决于使用量)
- **代理费用**: $0 (已禁用)
- **总成本**: 比使用代理便宜 60-80%

## 🔄 后续扩展

如果后续需要启用代理功能：
1. 修改环境变量: `DISABLE_PROXY=false`
2. 配置代理池: 编辑 `proxies.txt`
3. 重新部署服务

---

**优势**: 部署简单、成本低、稳定性高、延迟最低
**适用场景**: 中小规模抓取、成本敏感、追求稳定性
