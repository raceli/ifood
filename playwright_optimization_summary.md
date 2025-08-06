# Playwright 在 Google Cloud Functions 中的优化总结

## 参考资料
基于 [Browserless 博客文章](https://www.browserless.io/blog/playwright-on-google-cloud) 的最佳实践

## 主要优化内容

### 1. 浏览器启动参数优化
- 使用 `_get_optimized_browser_args()` 函数提供针对 Cloud Function 环境的优化参数
- 基础参数包含内存和资源优化选项
- Cloud Function 环境特定参数：
  - `--single-process` - 减少内存占用
  - `--disable-images` - 禁用图片加载提高速度
  - `--disable-web-security` - 绕过安全限制
  - `--window-size=1280,720` - 设置较小窗口尺寸

### 2. 浏览器启动后备策略
实现了 `_launch_browser_with_fallback()` 函数，包含多重启动策略：
1. **标准启动** - 使用完整优化参数
2. **最小化启动** - 使用最基本参数
3. **动态安装后启动** - 运行时安装浏览器
4. **系统浏览器启动** - 使用预装浏览器

### 3. 页面配置优化
- 设置较小的视口 (1280x720) 以节省内存
- 增加导航超时时间 (45秒) 和默认超时 (30秒)
- 在 Cloud Function 环境中阻止图片和 CSS 请求以提高性能
- 优化 API 响应等待超时时间 (35秒)

### 4. 错误处理和资源管理
- 详细的错误分类：TimeoutError、NetworkError、BrowserError、MemoryError
- 集成 psutil 监控内存使用
- 改进的资源清理：先关闭页面上下文，再关闭浏览器
- 在 Cloud Function 环境中强制垃圾回收

### 5. Cloud Function 配置优化
更新了部署配置以匹配 Browserless 建议：
- **内存**: 从 2GB 增加到 4GB
- **超时**: 从 540秒 增加到 600秒
- **并发**: 设置为 1 以避免内存竞争
- **CPU**: 设置为 2 核心
- **运行时**: 使用 Python 3.11

### 6. 依赖管理
- 添加 `psutil` 依赖用于内存监控
- 移除不必要的 `requests` 依赖
- 保持 `playwright` 作为主要依赖

## 部署配置变更

### 部署命令优化
```bash
gcloud functions deploy ifood-scraper \
  --gen2 \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --memory 4GB \
  --timeout 600s \
  --max-instances 10 \
  --min-instances 0 \
  --concurrency 1 \
  --cpu 2 \
  --region us-central1
```

### 环境变量配置
- 保持 GCP 自然 IP 轮换启用
- 优化日志级别配置
- 支持可选的云代理配置

## 预期改进

1. **性能提升**
   - 更快的浏览器启动时间
   - 减少内存占用和泄漏
   - 更稳定的页面导航

2. **可靠性增强**
   - 多重启动后备策略
   - 更好的错误处理和恢复
   - 详细的错误分类和调试信息

3. **资源效率**
   - 优化的浏览器参数
   - 自动资源清理
   - 内存使用监控

4. **维护性**
   - 模块化的配置函数
   - 清晰的错误日志
   - 符合最佳实践的代码结构

## 下一步建议

1. 测试优化后的配置在实际 Cloud Function 环境中的表现
2. 监控内存使用和函数执行时间
3. 根据实际使用情况调整超时和内存配置
4. 考虑使用 Browserless 托管服务作为替代方案（如果需要更高的可靠性）

## 注意事项
- 这些优化主要针对 Google Cloud Functions 环境
- 某些配置可能需要根据具体使用场景调整
- 建议先在测试环境中验证配置的有效性

## 部署修复说明

### 问题
部署时出现错误：`--docker-repository: Bad value [gcr.io/...]`，因为 Google Cloud 已经从 Container Registry 迁移到 Artifact Registry。

### 解决方案
已更新 `deploy_to_cloud_function.sh` 脚本：

1. **更新 Docker 镜像标签格式**：
   ```bash
   # 旧格式
   docker build -t gcr.io/$PROJECT_ID/${FUNCTION_NAME} .
   
   # 新格式  
   docker build -t ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}/image .
   ```

2. **更新 Docker 仓库配置**：
   ```bash
   # 旧格式
   --docker-repository gcr.io/$PROJECT_ID/${FUNCTION_NAME}
   
   # 新格式
   --docker-repository ${REGION}-docker.pkg.dev/$PROJECT_ID/${FUNCTION_NAME}
   ```

3. **移除不兼容参数**：
   - 移除 `--docker-registry artifact-registry` 参数（Cloud Functions 2nd gen 不支持）
   - 只保留 `--docker-repository` 参数

4. **添加 Artifact Registry 支持**：
   - 启用 `artifactregistry.googleapis.com` API
   - 自动创建 Docker 仓库（如果不存在）

### 部署命令
现在可以重新运行部署脚本：
```bash
./deploy_to_cloud_function.sh [项目ID] [函数名称]
```

### 注意事项
- 确保项目有足够的权限创建 Artifact Registry 仓库
- 首次部署可能需要几分钟来创建仓库
- 如果仓库已存在，脚本会跳过创建步骤

## Cloud Function 浏览器路径修复

### 问题
Cloud Function 运行时出现错误：
```
Executable doesn't exist at /www-data-home/.cache/ms-playwright/chromium_headless_shell-1181/chrome-linux/headless_shell
```

### 解决方案
已更新 Dockerfile 和 api.py：

1. **Dockerfile 优化**：
   - 添加完整的 Playwright 系统依赖
   - 使用 `--with-deps` 参数安装 Chromium
   - 设置 `PLAYWRIGHT_BROWSERS_PATH` 环境变量
   - 验证浏览器安装

2. **api.py 启动策略优化**：
   - 添加 "Cloud Function 浏览器启动" 策略
   - 使用通配符路径查找实际浏览器位置
   - 改进动态安装逻辑
   - 增强错误处理和日志记录

### 修复内容
- **Dockerfile**: 添加 30+ 个系统依赖包
- **api.py**: 新增浏览器路径查找逻辑
- **环境变量**: 设置正确的浏览器路径

### 重新部署
```bash
# 重新构建和部署
./deploy_to_cloud_function.sh
```