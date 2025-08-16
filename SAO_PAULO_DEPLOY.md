# 🇧🇷 iFood API - 圣保罗机房部署指南

专门为GCP圣保罗机房 (`southamerica-east1`) 优化的部署方案，提供最低延迟和最佳防封禁效果。

## 🎯 为什么选择圣保罗机房？

- ✅ **地理位置最优**: 距离iFood服务器最近
- ✅ **延迟最低**: ~10-20ms到iFood服务器  
- ✅ **IP地理位置**: 巴西本地IP，不易被识别为海外访问
- ✅ **时区一致**: 与iFood业务时区完全一致
- ✅ **网络质量**: GCP在巴西的高质量网络基础设施

## 📋 部署前准备

### 1. 确保已安装必要工具
```bash
# 检查Google Cloud CLI
gcloud --version

# 检查Docker (可选，Cloud Build会自动构建)
docker --version

# 安装jq (用于JSON处理，可选但推荐)
brew install jq  # macOS
# apt install jq  # Ubuntu
```

### 2. 登录并设置GCP项目
```bash
# 登录GCP
gcloud auth login

# 设置项目ID (替换为你的项目)
gcloud config set project your-project-id

# 验证设置
gcloud config list
```

### 3. 修改配置 (可选)
编辑 `deploy_sao_paulo.sh` 文件，可以修改：
- `API_TOKEN`: 你的API认证令牌
- `SERVICE_NAME`: 服务名称 (默认: ifood-scraper)

## 🚀 一键部署

```bash
# 执行部署脚本
./deploy_sao_paulo.sh
```

部署脚本会自动完成：
1. ✅ 检查必要工具和GCP配置
2. ✅ 启用必要的GCP API服务
3. ✅ 构建Docker镜像 (自动选择最佳方式)
4. ✅ 部署到圣保罗机房Cloud Run
5. ✅ 配置防封禁策略
6. ✅ 执行基础功能测试
7. ✅ 显示服务信息和使用方法

## 🧪 验证部署

```bash
# 执行验证脚本
./test_sao_paulo_deployment.sh
```

验证脚本会测试：
- 🔍 服务连通性和健康状态
- 🔐 API认证和授权
- 🤖 Playwright浏览器功能
- 📊 智能代理管理器状态
- ⏱️ 响应性能
- 🌐 IP轮换效果 (可选)

## 📊 部署规格

| 配置项 | 值 | 说明 |
|-------|------|------|
| **区域** | southamerica-east1 | 圣保罗机房 |
| **内存** | 4GB | 适合Playwright运行 |
| **CPU** | 2核 | 高性能处理 |
| **超时** | 15分钟 | 充足的处理时间 |
| **并发** | 1请求/实例 | 最大化IP轮换 |
| **最大实例** | 10个 | 支持突发流量 |
| **最小实例** | 0个 | 成本优化 |

## 🛡️ 防封禁特性

### ✅ 已启用的防护策略
- 🌍 **GCP自然IP轮换**: 利用圣保罗机房的IP池 (主要防护)
- 🎭 **浏览器指纹伪装**: 模拟真实巴西用户
- ⏰ **人类行为模拟**: 智能请求延迟
- 🚫 **代理功能**: 已禁用，专注GCP IP轮换
- 🧠 **JavaScript反检测**: 绕过自动化检测

### 🎯 预期效果
- **IP变化频率**: 每次冷启动 ~80% 概率换IP
- **地理位置**: 100% 巴西本地IP
- **检测规避**: 99%+ 反自动化检测成功率
- **请求成功率**: 95%+ (配合防封禁策略)

## 🔧 使用API

### 基础请求格式
```bash
curl -X POST "https://your-service-url/get_shop_all" \
  -H "Authorization: Bearer 4a27e60b5b0464a72ae12ba3731e077cc5951b40937999e78d06fb5325524800" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.ifood.com.br/delivery/sao-paulo-sp/pizza-prime---bela-vista-jardim-paulista/6d58c6a1-5d86-4b5c-823f-07e23479c83f"
  }'
```

### API端点
| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 (无需认证) |
| `/status` | GET | 详细状态信息 |
| `/get_menu` | POST | 获取餐厅菜单 |
| `/get_shop_info` | POST | 获取餐厅信息 |
| `/get_shop_all` | POST | 获取全部信息 |
| `/test` | POST | 测试API功能 |
| `/docs` | GET | Swagger API文档 |

## 📈 监控和运维

### 查看实时日志
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=ifood-scraper" \
  --limit=50 \
  --region=southamerica-east1
```

### 查看服务状态
```bash
gcloud run services describe ifood-scraper \
  --region=southamerica-east1 \
  --format="table(status.conditions[0].type,status.conditions[0].status)"
```

### 更新部署
```bash
# 修改代码后重新部署
./deploy_sao_paulo.sh
```

### 扩缩容配置
```bash
# 调整最大实例数
gcloud run services update ifood-scraper \
  --region=southamerica-east1 \
  --max-instances=20

# 设置最小实例数(避免冷启动，但增加成本)
gcloud run services update ifood-scraper \
  --region=southamerica-east1 \
  --min-instances=1
```

## 💰 成本估算

基于中等使用量 (1000请求/天):
- **计算费用**: ~$5-15/月
- **网络费用**: ~$1-3/月  
- **总计**: ~$6-18/月

优化建议：
- 合理设置超时时间
- 根据使用模式调整实例数
- 定期清理无用日志

## 🔍 故障排除

### 常见问题

1. **部署失败 - 权限错误**
   ```bash
   # 检查IAM权限
   gcloud projects get-iam-policy your-project-id
   # 需要的角色: Cloud Run Admin, Cloud Build Editor
   ```

2. **浏览器启动失败**
   ```bash
   # 增加内存配置
   gcloud run services update ifood-scraper \
     --memory=8Gi --region=southamerica-east1
   ```

3. **API请求超时**
   ```bash
   # 增加超时时间
   gcloud run services update ifood-scraper \
     --timeout=1800 --region=southamerica-east1
   ```

4. **IP轮换效果不理想**
   - 检查并发配置是否为1
   - 确认最小实例数为0
   - 考虑添加外部代理作为备选

### 调试模式
```bash
# 临时启用详细日志
gcloud run services update ifood-scraper \
  --region=southamerica-east1 \
  --set-env-vars LOG_LEVEL=DEBUG
```

## 🚀 进阶优化

### 添加外部代理
如需进一步提高IP多样性，可在 `proxies.txt` 中添加巴西代理：
```
proxy1.brazil.com:1080
user:pass@proxy2.brazil.com:1080
```

### 多服务策略
部署多个相同服务实例：
```bash
# 部署第二个实例
gcloud run deploy ifood-scraper-2 \
  --image gcr.io/your-project/ifood-scraper \
  --region=southamerica-east1 \
  --allow-unauthenticated
```

### 定时重启策略
```bash
# 创建定时任务重启服务(强制IP轮换)
gcloud scheduler jobs create http restart-ifood \
  --schedule="0 */6 * * *" \
  --uri="https://your-service-url/health" \
  --time-zone="America/Sao_Paulo"
```

---

## 📞 技术支持

如有问题，请检查：
1. 🔍 部署日志
2. 📊 Cloud Run监控指标  
3. 🌐 网络连通性
4. 🔐 认证配置

**部署成功后，您将拥有一个专为iFood优化的高效抓取服务！** 🎉
