#!/bin/bash

# iFood抓取API - 圣保罗机房部署脚本
# 部署到 southamerica-east1 (São Paulo, Brazil)
# 这是距离iFood服务器最近的GCP区域，可获得最低延迟

set -e

# 🎯 配置参数
PROJECT_ID="your-project-id"  # 替换为你的GCP项目ID
SERVICE_NAME="ifood-scraper"
REGION="southamerica-east1"  # 圣保罗机房
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# 🔐 API认证令牌 (建议使用强密码)
API_TOKEN="4a27e60b5b0464a72ae12ba3731e077cc5951b40937999e78d06fb5325524800"

# 🎨 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

echo_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

echo_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 检查必要工具
check_requirements() {
    echo_info "检查必要工具..."
    
    if ! command -v gcloud &> /dev/null; then
        echo_error "gcloud CLI 未安装，请先安装 Google Cloud CLI"
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        echo_warning "Docker 未安装，将使用 Cloud Build 构建镜像"
    fi
    
    echo_success "必要工具检查完成"
}

# 验证GCP配置
check_gcp_config() {
    echo_info "验证GCP配置..."
    
    # 检查是否已登录
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
        echo_error "请先登录GCP: gcloud auth login"
        exit 1
    fi
    
    # 检查项目ID设置
    current_project=$(gcloud config get-value project 2>/dev/null || echo "")
    if [[ -z "$current_project" ]]; then
        echo_error "请先设置GCP项目: gcloud config set project YOUR_PROJECT_ID"
        exit 1
    fi
    
    echo_success "当前GCP项目: $current_project"
    PROJECT_ID=$current_project
    IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
}

# 启用必要的API服务
enable_apis() {
    echo_info "启用必要的GCP API服务..."
    
    gcloud services enable run.googleapis.com \
        cloudbuild.googleapis.com \
        containerregistry.googleapis.com \
        --quiet
    
    echo_success "API服务启用完成"
}

# 构建Docker镜像
build_image() {
    echo_info "构建Docker镜像..."
    
    if command -v docker &> /dev/null && docker info &> /dev/null; then
        echo_info "使用本地Docker构建..."
        docker build -t $IMAGE_NAME .
        docker push $IMAGE_NAME
    else
        echo_info "使用Cloud Build构建镜像..."
        gcloud builds submit --tag $IMAGE_NAME --quiet
    fi
    
    echo_success "镜像构建完成: $IMAGE_NAME"
}

# 部署到Cloud Run
deploy_service() {
    echo_info "部署到Cloud Run (圣保罗机房)..."
    
    # 添加时间戳强制创建新版本
    TIMESTAMP=$(date +%s)
    
    gcloud run deploy $SERVICE_NAME \
        --image $IMAGE_NAME \
        --platform managed \
        --region $REGION \
        --allow-unauthenticated \
        --memory 4Gi \
        --cpu 2 \
        --timeout 900 \
        --max-instances 10 \
        --min-instances 0 \
        --concurrency 1 \
        --port 8000 \
        --set-env-vars \
API_TOKEN="$API_TOKEN",\
USE_GCP_NATURAL_IP_ROTATION="true",\
LOG_LEVEL="INFO",\
FUNCTION_REGION="$REGION",\
DISABLE_PROXY="true",\
DEPLOY_TIMESTAMP="$TIMESTAMP" \
        --no-traffic \
        --tag="v$TIMESTAMP" \
        --quiet
    
    # 将流量切换到新版本
    echo_info "将流量切换到新版本..."
    gcloud run services update-traffic $SERVICE_NAME \
        --to-tags="v$TIMESTAMP=100" \
        --region=$REGION \
        --quiet
    
    echo_success "服务部署完成"
}

# 获取服务URL
get_service_url() {
    echo_info "获取服务URL..."
    
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format='value(status.url)')
    
    echo_success "服务URL: $SERVICE_URL"
    return 0
}

# 测试部署
test_deployment() {
    echo_info "测试部署..."
    
    # 健康检查
    echo_info "执行健康检查..."
    if curl -s "${SERVICE_URL}/health" > /dev/null; then
        echo_success "健康检查通过"
    else
        echo_warning "健康检查失败，服务可能仍在启动中"
    fi
    
    # API测试
    echo_info "测试API功能..."
    test_response=$(curl -s -X POST "${SERVICE_URL}/test" \
        -H "Authorization: Bearer $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{}' || echo "")
    
    if [[ -n "$test_response" ]]; then
        echo_success "API测试通过"
        echo "测试响应: $(echo $test_response | jq -r '.status // .message // .' 2>/dev/null || echo $test_response)"
    else
        echo_warning "API测试失败，请检查日志"
    fi
}

# 显示部署信息
show_deployment_info() {
    echo ""
    echo "🎉 部署完成！"
    echo "────────────────────────────────────────"
    echo "📍 服务名称: $SERVICE_NAME"
    echo "🌎 部署区域: $REGION (圣保罗机房)"
    echo "🔗 服务URL: $SERVICE_URL"
    echo "🔐 API Token: $API_TOKEN"
    echo ""
    echo "📖 API文档: ${SERVICE_URL}/docs"
    echo "💚 健康检查: ${SERVICE_URL}/health"
    echo "📊 状态信息: ${SERVICE_URL}/status"
    echo ""
    echo "🧪 测试命令:"
    echo "curl -X POST \"${SERVICE_URL}/get_shop_all\" \\"
    echo "  -H \"Authorization: Bearer $API_TOKEN\" \\"
    echo "  -H \"Content-Type: application/json\" \\"
    echo "  -d '{\"url\": \"https://www.ifood.com.br/delivery/sao-paulo-sp/pizza-prime---bela-vista-jardim-paulista/6d58c6a1-5d86-4b5c-823f-07e23479c83f\"}'"
    echo ""
    echo "📝 查看日志:"
    echo "gcloud logging read \"resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME\" --limit=50"
    echo ""
    echo "🚀 防封禁特性已启用:"
    echo "  ✅ GCP自然IP轮换 (圣保罗机房)"
    echo "  🚫 代理功能已禁用 (专注GCP IP轮换)"
    echo "  ✅ 浏览器指纹伪装"
    echo "  ✅ 人类行为模拟"
    echo "  ✅ JavaScript反检测"
}

# 主函数
main() {
    echo "🚀 开始部署iFood抓取API到GCP圣保罗机房..."
    echo ""
    
    check_requirements
    check_gcp_config
    enable_apis
    build_image
    deploy_service
    get_service_url
    test_deployment
    show_deployment_info
    
    echo_success "🎊 部署流程全部完成！"
}

# 错误处理
trap 'echo_error "部署过程中发生错误，请检查上面的日志"; exit 1' ERR

# 执行主函数
main "$@"
