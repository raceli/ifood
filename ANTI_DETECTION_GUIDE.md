# 🛡️ iFood API 防封禁完整指南

本文档详细介绍了如何防止被iFood网站的安全策略封禁，包括已实现的策略和进一步优化建议。

## 📊 当前已实现的防封策略

### 1. 🔒 增强的浏览器指纹伪装

**实现位置**: `stealth_config.py`

- ✅ **禁用自动化特征**: `--disable-blink-features=AutomationControlled`
- ✅ **随机User-Agent**: 模拟Windows/macOS真实用户
- ✅ **随机视口尺寸**: 1920x1080、1366x768、1440x900等
- ✅ **真实HTTP请求头**: 包含Accept、Accept-Language等
- ✅ **JavaScript反检测脚本**: 移除webdriver特征、伪造Chrome运行时

### 2. ⏱️ 人类行为模拟

**实现位置**: `api.py` 各端点函数

- ✅ **智能延迟**: 1.5-12秒随机延迟，权重分布模拟真实用户
- ✅ **请求间隔**: 每个API请求前都有人类行为延迟
- ✅ **真实时区**: 使用巴西时区 `America/Sao_Paulo`

### 3. 🌐 智能代理轮换

**实现位置**: `proxy_manager.py`

- ✅ **智能选择算法**: 基于成功率、响应时间、使用频率
- ✅ **健康检查**: 自动检测和屏蔽失效代理
- ✅ **失败重试**: 连续失败后临时屏蔽代理
- ✅ **统计分析**: 实时监控代理性能

### 4. 🎭 浏览器环境伪装

**实现位置**: `stealth_config.py`

- ✅ **内存配置**: 8GB/16GB模拟真实设备
- ✅ **CPU核心数**: 4/8核模拟
- ✅ **平台识别**: Windows/macOS Platform信息
- ✅ **语言设置**: 葡萄牙语优先 `pt-BR,pt;q=0.9,en;q=0.8`

## 🚀 使用方法

### 1. 启动API服务
```bash
# 安装依赖
pip install -r requirements.txt

# 安装Playwright浏览器
playwright install chromium

# 启动服务
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

### 2. 配置代理（可选但强烈推荐）
在 `proxies.txt` 文件中添加SOCKS5代理：
```
proxy1.example.com:1080
user:pass@proxy2.example.com:1080
```

### 3. 使用API
```bash
curl -X 'POST' \
  'http://localhost:8000/get_shop_all' \
  -H 'Authorization: Bearer local-dev-token' \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.ifood.com.br/delivery/..."}'
```

### 4. 监控代理状态
```bash
curl -X 'GET' \
  'http://localhost:8000/status' \
  -H 'Authorization: Bearer local-dev-token'
```

## ⚙️ 高级配置

### 代理轮换策略
在环境变量中设置：
```bash
# 智能选择（推荐）
export PROXY_ROTATION_STRATEGY="smart"

# 随机选择
export PROXY_ROTATION_STRATEGY="random"

# 轮询
export PROXY_ROTATION_STRATEGY="round_robin"

# 会话固定
export PROXY_ROTATION_STRATEGY="session"
```

### 云环境优化
```bash
# Cloud Function环境变量
export FUNCTION_TARGET="main"
export GCP_REGION="us-central1"
export USE_GCP_NATURAL_IP_ROTATION="true"
```

## 🔥 进一步优化建议

### 1. 添加Playwright Stealth插件（可选）

为了进一步增强反检测能力，可以安装 `playwright-stealth` 插件：

```bash
# 安装stealth插件
npm install playwright-stealth

# 或者使用Python版本（如果有的话）
pip install playwright-stealth
```

然后在代码中启用：
```python
from playwright_stealth import stealth

async def enhanced_page_setup(page):
    await stealth(page)
    # ... 其他配置
```

### 2. 请求频率控制

- **高峰时段避免**: 避免在巴西时间工作时间大量请求
- **分布式请求**: 使用多个IP地址分散请求
- **缓存策略**: 对相同URL实现缓存，减少重复请求

### 3. 监控和告警

- **403状态码监控**: 及时发现被封禁的代理
- **响应时间监控**: 检测性能下降
- **成功率告警**: 成功率低于阈值时告警

## 📈 性能指标

### 代理健康度指标
- **成功率**: > 70%
- **平均响应时间**: < 5秒
- **连续失败次数**: < 5次

### 系统监控
可通过 `/status` 端点查看：
- 代理统计信息
- 系统资源使用
- 请求成功率

## ⚠️ 注意事项

### 1. 合规使用
- 遵守网站服务条款
- 合理控制请求频率
- 不进行恶意爬取

### 2. 技术限制
- 部分反检测技术可能被检测
- 需要持续更新策略
- 代理质量直接影响成功率

### 3. 成本考虑
- 优质代理服务需要费用
- 云环境资源消耗
- 维护和监控成本

## 🔧 故障排除

### 常见问题

1. **所有代理都被封禁**
   - 检查代理质量
   - 降低请求频率
   - 更换代理提供商

2. **浏览器启动失败**
   - 检查Playwright安装
   - 验证系统依赖
   - 查看内存使用情况

3. **请求超时**
   - 检查网络连接
   - 调整超时配置
   - 验证目标URL有效性

### 调试技巧
- 启用详细日志
- 使用浏览器可见模式调试
- 监控网络请求

## 📞 技术支持

如遇到问题，请：
1. 检查日志文件
2. 验证配置是否正确
3. 测试代理连接性
4. 查看系统资源使用情况

---

**免责声明**: 本工具仅供学习和研究使用，请遵守相关法律法规和网站服务条款。
