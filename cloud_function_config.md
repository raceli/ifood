# Cloud Function 代理配置指南

## 环境变量配置

在Cloud Function中设置以下环境变量来配置云代理：

### 必需的环境变量
```bash
# API认证令牌
API_TOKEN=your-super-secret-token

# 云代理配置
CLOUD_PROXY_USERNAME=your_proxy_username
CLOUD_PROXY_PASSWORD=your_proxy_password
CLOUD_PROXY_HOST=proxy.provider.com
CLOUD_PROXY_PORT=1080

# 代理轮换策略 (可选)
PROXY_ROTATION_STRATEGY=random  # random, sequential, session
```

## 推荐的云代理服务

### 1. Bright Data (Luminati)
- **优点**: IP池大，地理位置覆盖广，支持住宅IP
- **价格**: 较高，但质量好
- **配置示例**:
```bash
CLOUD_PROXY_HOST=brd.superproxy.io
CLOUD_PROXY_PORT=22225
CLOUD_PROXY_USERNAME=brd-customer-{country}-zone-{zone}-session-{session}
CLOUD_PROXY_PASSWORD=your_password
```

### 2. Oxylabs
- **优点**: 住宅代理网络，反检测能力强
- **价格**: 中等
- **配置示例**:
```bash
CLOUD_PROXY_HOST=pr.oxylabs.io
CLOUD_PROXY_PORT=7777
CLOUD_PROXY_USERNAME=your_username
CLOUD_PROXY_PASSWORD=your_password
```

### 3. SmartProxy
- **优点**: 性价比高，简单易用
- **价格**: 较低
- **配置示例**:
```bash
CLOUD_PROXY_HOST=gate.smartproxy.com
CLOUD_PROXY_PORT=7000
CLOUD_PROXY_USERNAME=your_username
CLOUD_PROXY_PASSWORD=your_password
```

## Google Cloud Function 部署

### 1. 设置环境变量
```bash
gcloud functions deploy ifood-api \
  --runtime python39 \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars API_TOKEN=your-token,CLOUD_PROXY_USERNAME=your-username,CLOUD_PROXY_PASSWORD=your-password,CLOUD_PROXY_HOST=proxy.provider.com,CLOUD_PROXY_PORT=1080
```

### 2. 或者通过控制台设置
1. 进入Google Cloud Console
2. 选择您的Cloud Function
3. 点击"编辑"
4. 在"环境变量"部分添加上述变量

## 代理轮换策略

### random (默认)
- 每次请求随机选择IP
- 适合高频率请求

### sequential  
- 按顺序使用IP池
- 适合需要稳定性的场景

### session
- 同一会话使用相同IP
- 适合需要保持会话的场景

## 注意事项

1. **成本控制**: 云代理按流量计费，注意监控使用量
2. **IP质量**: 住宅IP比数据中心IP更不容易被检测
3. **地理位置**: 选择目标网站所在地区的IP
4. **并发限制**: 注意代理服务的并发连接数限制
5. **错误处理**: 代码已包含代理失败时的回退机制

## 测试代理配置

部署后可以通过以下方式测试：

```bash
curl -X POST "https://your-function-url/get_menu" \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.ifood.com.br/restaurante/example"}'
```

检查日志确认代理是否正常工作。 