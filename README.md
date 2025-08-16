# iFood Menu API

一个基于 Playwright 的 iFood 菜单抓取 API 服务，支持代理轮换和 Cloud Function 部署。

## 🚀 功能特性

- **智能代理轮换**: 支持本地代理文件、云代理服务和 GCP 自然 IP 轮换
- **Cloud Function 优化**: 专门针对 Google Cloud Functions 环境优化
- **多端点支持**: 菜单、店铺信息、完整信息获取
- **健康检查**: 内置健康检查和状态监控
- **认证保护**: Bearer Token 认证机制
- **错误处理**: 完善的错误处理和日志记录

## 📋 环境要求

- Python 3.8+
- Playwright
- FastAPI
- 代理服务器（可选）

## 🛠️ 安装步骤

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 安装 Playwright 浏览器

```bash
playwright install chromium
```

### 3. 配置代理（可选）

创建 `proxies.txt` 文件，每行一个代理：

```
proxy1.example.com:1080
proxy2.example.com:1080
# 这是注释行
```

### 4. 设置环境变量

```bash
# API 认证令牌
export API_TOKEN="your-secret-token"

# 云代理配置（可选）
export CLOUD_PROXY_USERNAME="username"
export CLOUD_PROXY_PASSWORD="password"
export CLOUD_PROXY_HOST="proxy.example.com"
export CLOUD_PROXY_PORT="1080"

# 代理轮换策略
export PROXY_ROTATION_STRATEGY="random"  # random, sequential, session

# GCP 配置（Cloud Function 环境）
export USE_GCP_NATURAL_IP_ROTATION="true"
```

## 🚀 运行服务

### 方法 1: 直接运行

```bash
python api.py
```

### 方法 2: 使用 uvicorn

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后，访问 http://localhost:8000/docs 查看 API 文档。

## 📚 API 端点

### 健康检查

```bash
GET /health
```

返回服务状态和系统信息。

### 状态信息

```bash
GET /status
Authorization: Bearer your-secret-token
```

返回详细的系统状态信息。

### 测试功能

```bash
POST /test
Authorization: Bearer your-secret-token
```

测试代理和浏览器功能是否正常。

### 获取菜单

```bash
POST /get_menu
Authorization: Bearer your-secret-token
Content-Type: application/json

{
    "url": "https://www.ifood.com.br/delivery/sao-paulo-sp/restaurant-name"
}
```

### 获取店铺信息

```bash
POST /get_shop_info
Authorization: Bearer your-secret-token
Content-Type: application/json

{
    "url": "https://www.ifood.com.br/delivery/sao-paulo-sp/restaurant-name"
}
```

### 获取完整信息

```bash
POST /get_shop_all
Authorization: Bearer your-secret-token
Content-Type: application/json

{
    "url": "https://www.ifood.com.br/delivery/sao-paulo-sp/restaurant-name"
}
```

## ☁️ Cloud Function 部署

### 1. 准备部署文件

确保以下文件存在：
- `api.py` - 主应用文件
- `main.py` - Cloud Function 入口点
- `requirements.txt` - 依赖文件
- `cloud_function_deploy.yaml` - 环境配置

### 2. 部署到 Cloud Function

```bash
# 使用 gcloud CLI 部署
gcloud functions deploy ifood-api \
    --runtime python39 \
    --trigger-http \
    --allow-unauthenticated \
    --memory 4GB \
    --timeout 600s \
    --entry-point get_menu_endpoint_sync \
    --source . \
    --region us-central1
```

### 3. 设置环境变量

```bash
gcloud functions deploy ifood-api \
    --update-env-vars API_TOKEN=your-secret-token,USE_GCP_NATURAL_IP_ROTATION=true
```

## 🔧 配置说明

### 代理策略

- **random**: 随机选择代理（默认）
- **sequential**: 按顺序使用代理
- **session**: 会话期间使用同一代理

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `API_TOKEN` | API 认证令牌 | `local-dev-token` |
| `CLOUD_PROXY_USERNAME` | 云代理用户名 | - |
| `CLOUD_PROXY_PASSWORD` | 云代理密码 | - |
| `CLOUD_PROXY_HOST` | 云代理主机 | - |
| `CLOUD_PROXY_PORT` | 云代理端口 | `1080` |
| `PROXY_ROTATION_STRATEGY` | 代理轮换策略 | `random` |
| `USE_GCP_NATURAL_IP_ROTATION` | 使用 GCP IP 轮换 | `true` |

## 📊 性能优化

### Cloud Function 优化

- 使用单进程模式减少内存占用
- 禁用图片和 CSS 加载提高速度
- 优化浏览器启动参数
- 自动垃圾回收

### 代理优化

- 智能代理选择策略
- 自动故障转移
- 连接超时处理

## 🐛 故障排除

### 常见问题

1. **浏览器启动失败**
   - 检查 Playwright 是否正确安装
   - 在 Cloud Function 中可能需要动态安装浏览器

2. **代理连接失败**
   - 验证代理服务器是否可用
   - 检查代理格式是否正确

3. **超时错误**
   - 增加超时时间设置
   - 检查网络连接

4. **内存不足**
   - 增加 Cloud Function 内存配置
   - 优化浏览器参数

### 日志查看

```bash
# 本地运行
tail -f /tmp/ifood_api.log

# Cloud Function
gcloud functions logs read ifood-api --limit 50
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！ 