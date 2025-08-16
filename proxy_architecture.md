# iFood 代理服务架构设计

## 🏗️ 架构概述

这个方案将 Playwright 浏览器服务部署在 Google Cloud Functions 上，作为代理服务，让部署在 K8s 上的其他服务通过 HTTP API 访问 iFood 网页。

```
┌─────────────────┐    HTTP API    ┌─────────────────────┐
│   K8s 服务      │ ──────────────► │  Cloud Function     │
│                 │                │   代理服务          │
│ - 数据采集服务   │                │ - Playwright 浏览器 │
│ - 分析服务      │                │ - 网页渲染          │
│ - API 服务      │                │ - 内容提取          │
└─────────────────┘                └─────────────────────┘
                                              │
                                              ▼
                                    ┌─────────────────┐
                                    │   iFood 网站    │
                                    │                 │
                                    └─────────────────┘
```

## 🎯 优势

### 1. **架构分离**
- **Cloud Function**: 专门处理浏览器相关任务
- **K8s 服务**: 专注于业务逻辑和数据处理
- **职责清晰**: 每个组件专注于自己的核心功能

### 2. **资源优化**
- **Cloud Function**: 按需启动，自动扩缩容
- **K8s 服务**: 轻量化，不需要浏览器依赖
- **成本控制**: 只在需要时消耗浏览器资源

### 3. **维护简单**
- **浏览器管理**: 集中在 Cloud Function 中
- **更新方便**: 独立部署和更新
- **故障隔离**: 浏览器问题不影响 K8s 服务

### 4. **扩展性好**
- **多实例**: Cloud Function 自动处理并发
- **负载均衡**: 天然支持负载分散
- **监控**: 独立的监控和日志

## 📁 文件结构

```
ifood/
├── proxy_service.py          # 代理服务核心逻辑
├── proxy_main.py            # Cloud Function 入口点
├── deploy_proxy_service.sh   # 代理服务部署脚本
├── k8s_client_example.py    # K8s 客户端示例
├── proxy_architecture.md    # 架构说明文档
├── Dockerfile               # 容器配置
├── requirements.txt         # 依赖配置
└── cloud_function_deploy.yaml # 环境变量配置
```

## 🚀 部署步骤

### 1. 部署代理服务到 Cloud Function

```bash
# 给部署脚本执行权限
chmod +x deploy_proxy_service.sh

# 部署代理服务
./deploy_proxy_service.sh [项目ID] [函数名称]
```

### 2. 在 K8s 中使用代理服务

```python
# 使用客户端示例
from k8s_client_example import IFoodProxyClient

# 创建客户端
client = IFoodProxyClient("https://your-proxy-url.cloudfunctions.net/ifood-proxy")

# 获取餐厅菜单
menu = client.get_ifood_menu("https://www.ifood.com.br/restaurant/...")
```

## 🔧 API 端点

### 1. 健康检查
```
GET /ifood-proxy-health
```

### 2. 测试端点
```
GET /ifood-proxy-test
```

### 3. 简单代理
```
POST /ifood-proxy-simple
{
    "url": "https://www.ifood.com.br",
    "timeout": 30
}
```

### 4. 完整代理
```
POST /ifood-proxy-proxy
{
    "url": "https://www.ifood.com.br",
    "method": "GET",
    "timeout": 30,
    "wait_for_selector": "h2.restaurant-menu__category-title",
    "extract_text": true,
    "screenshot": false
}
```

## 📊 性能特点

### 响应时间
- **冷启动**: 5-10秒 (首次请求)
- **热启动**: 1-3秒 (后续请求)
- **页面加载**: 2-5秒 (取决于目标网站)

### 并发能力
- **Cloud Function**: 支持 10 个并发实例
- **内存配置**: 4GB (足够运行浏览器)
- **超时设置**: 600秒 (10分钟)

### 成本估算
- **Cloud Function**: 按请求和内存时间计费
- **典型成本**: $0.01-0.05 每次请求
- **优化建议**: 使用缓存减少重复请求

## 🔒 安全考虑

### 1. **访问控制**
- 可以添加 API 密钥认证
- 支持 IP 白名单限制
- 可以集成 Google Cloud IAM

### 2. **数据安全**
- HTTPS 传输加密
- 敏感数据不持久化
- 临时文件自动清理

### 3. **资源限制**
- 请求超时限制
- 内存使用限制
- 并发请求限制

## 🛠️ 使用示例

### 在 K8s Pod 中使用

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ifood-data-collector
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ifood-data-collector
  template:
    metadata:
      labels:
        app: ifood-data-collector
    spec:
      containers:
      - name: data-collector
        image: your-registry/ifood-collector:latest
        env:
        - name: PROXY_URL
          value: "https://us-central1-your-project.cloudfunctions.net/ifood-proxy"
        - name: API_TOKEN
          valueFrom:
            secretKeyRef:
              name: ifood-secrets
              key: api-token
```

### 在 Python 服务中使用

```python
import requests
import json

class IFoodDataCollector:
    def __init__(self, proxy_url: str):
        self.proxy_url = proxy_url
    
    def collect_menu_data(self, restaurant_url: str):
        """收集餐厅菜单数据"""
        response = requests.post(
            f"{self.proxy_url}-proxy",
            json={
                "url": restaurant_url,
                "method": "GET",
                "timeout": 60,
                "wait_for_selector": "h2.restaurant-menu__category-title",
                "extract_text": True,
                "extract_html": True
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            # 处理返回的数据
            return self.parse_menu_data(data['content'])
        else:
            raise Exception(f"代理请求失败: {response.text}")
    
    def parse_menu_data(self, html_content: str):
        """解析菜单数据"""
        # 使用 BeautifulSoup 或其他解析库
        # 这里实现具体的解析逻辑
        pass
```

## 🔄 监控和日志

### 1. **Cloud Function 监控**
- 请求数量
- 执行时间
- 错误率
- 内存使用

### 2. **日志记录**
- 请求日志
- 错误日志
- 性能指标
- 浏览器状态

### 3. **告警设置**
- 错误率告警
- 响应时间告警
- 资源使用告警

## 🚀 下一步计划

### 1. **功能增强**
- 添加更多浏览器选项
- 支持更多页面交互
- 增加缓存机制

### 2. **性能优化**
- 浏览器连接池
- 页面预加载
- 智能重试机制

### 3. **监控完善**
- 详细的性能指标
- 自动化告警
- 故障自愈

这个架构方案将复杂的浏览器管理从 K8s 服务中分离出来，提供了更好的可维护性和扩展性！ 