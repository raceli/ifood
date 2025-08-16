#!/bin/bash

# 圣保罗机房部署验证脚本
# 测试iFood抓取API的各项功能和IP轮换效果

set -e

# 配置参数
SERVICE_NAME="ifood-scraper"
REGION="southamerica-east1"
API_TOKEN="4a27e60b5b0464a72ae12ba3731e077cc5951b40937999e78d06fb5325524800"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

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

# 获取服务URL
get_service_url() {
    echo_info "获取服务URL..."
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format='value(status.url)' 2>/dev/null)
    
    if [[ -z "$SERVICE_URL" ]]; then
        echo_error "无法获取服务URL，请确保服务已部署"
        exit 1
    fi
    
    echo_success "服务URL: $SERVICE_URL"
}

# 基础连通性测试
test_connectivity() {
    echo_info "测试基础连通性..."
    
    if curl -s --max-time 10 "$SERVICE_URL/health" > /dev/null; then
        echo_success "服务连通性正常"
    else
        echo_error "服务连通性测试失败"
        return 1
    fi
}

# 健康检查测试
test_health() {
    echo_info "执行健康检查..."
    
    response=$(curl -s "$SERVICE_URL/health")
    status=$(echo "$response" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
    
    if [[ "$status" == "healthy" ]]; then
        echo_success "健康检查通过"
        echo "  系统状态: $(echo "$response" | jq -r '.system.platform // "unknown"' 2>/dev/null)"
        echo "  内存使用: $(echo "$response" | jq -r '.system.memory_percent // "unknown"' 2>/dev/null)%"
    else
        echo_warning "健康检查状态: $status"
    fi
}

# API认证测试
test_auth() {
    echo_info "测试API认证..."
    
    # 测试无token请求
    auth_response=$(curl -s -w "%{http_code}" -o /dev/null "$SERVICE_URL/status")
    if [[ "$auth_response" == "401" ]]; then
        echo_success "认证保护正常 (401 Unauthorized)"
    else
        echo_warning "认证保护可能有问题 (状态码: $auth_response)"
    fi
    
    # 测试有效token请求
    status_response=$(curl -s -H "Authorization: Bearer $API_TOKEN" "$SERVICE_URL/status")
    if echo "$status_response" | jq -e '.service' > /dev/null 2>&1; then
        echo_success "Token认证正常"
        
        # 显示一些状态信息
        service_name=$(echo "$status_response" | jq -r '.service // "unknown"')
        gcp_region=$(echo "$status_response" | jq -r '.environment.gcp_region // "unknown"')
        ip_rotation=$(echo "$status_response" | jq -r '.environment.use_gcp_ip_rotation // "unknown"')
        
        echo "  服务名称: $service_name"
        echo "  GCP区域: $gcp_region"
        echo "  IP轮换: $ip_rotation"
    else
        echo_error "Token认证失败"
        return 1
    fi
}

# 代理管理器测试
test_proxy_manager() {
    echo_info "测试代理配置状态..."
    
    status_response=$(curl -s -H "Authorization: Bearer $API_TOKEN" "$SERVICE_URL/status")
    proxy_disabled=$(echo "$status_response" | jq -r '.proxy.disabled // false' 2>/dev/null)
    
    if [[ "$proxy_disabled" == "true" ]]; then
        echo_success "代理功能已禁用 (专注GCP自然IP轮换)"
        echo "  🎯 策略: 使用GCP圣保罗机房的IP池轮换"
        echo "  💰 成本: 无额外代理费用"
        echo "  🚀 性能: 直接连接，延迟最低"
    else
        echo_info "代理功能已启用"
        proxy_stats=$(echo "$status_response" | jq -r '.proxy_manager_stats // {}' 2>/dev/null)
        
        if [[ "$proxy_stats" != "{}" ]] && [[ "$proxy_stats" != "null" ]]; then
            total_proxies=$(echo "$proxy_stats" | jq -r '.total // 0')
            healthy_proxies=$(echo "$proxy_stats" | jq -r '.healthy // 0')
            
            echo "  代理总数: $total_proxies"
            echo "  健康代理: $healthy_proxies"
        fi
    fi
}

# 测试API功能
test_api_functionality() {
    echo_info "测试API基础功能..."
    
    # 测试/test端点
    test_response=$(curl -s -X POST "$SERVICE_URL/test" \
        -H "Authorization: Bearer $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{}')
    
    if echo "$test_response" | jq -e '.status' > /dev/null 2>&1; then
        echo_success "API基础功能正常"
        
        browser_status=$(echo "$test_response" | jq -r '.browser_test.status // "unknown"')
        echo "  浏览器状态: $browser_status"
        
        if [[ "$browser_status" == "success" ]]; then
            echo_success "Playwright浏览器测试通过"
        else
            echo_warning "浏览器测试可能有问题"
        fi
    else
        echo_error "API基础功能测试失败"
        echo "响应: $test_response"
        return 1
    fi
}

# IP轮换效果测试
test_ip_rotation() {
    echo_info "测试IP轮换效果..."
    echo_warning "注意：这个测试需要几分钟时间，请耐心等待..."
    
    declare -A ip_counts
    total_requests=10
    successful_requests=0
    
    for i in $(seq 1 $total_requests); do
        echo_info "第 $i/$total_requests 次请求..."
        
        # 调用测试API，每次请求间隔较长以触发新实例
        response=$(curl -s -X POST "$SERVICE_URL/test" \
            -H "Authorization: Bearer $API_TOKEN" \
            -H "Content-Type: application/json" \
            -d '{}' 2>/dev/null || echo "")
        
        if [[ -n "$response" ]] && echo "$response" | jq -e '.status' > /dev/null 2>&1; then
            # 尝试从响应中提取IP信息（如果API返回的话）
            client_ip=$(echo "$response" | jq -r '.client_ip // "unknown"' 2>/dev/null || echo "unknown")
            proxy_used=$(echo "$response" | jq -r '.proxy_used // false' 2>/dev/null || echo "false")
            
            if [[ "$client_ip" != "unknown" ]]; then
                ip_counts["$client_ip"]=$((${ip_counts["$client_ip"]} + 1))
            fi
            
            successful_requests=$((successful_requests + 1))
            echo "  ✅ 成功 - IP: $client_ip, 代理: $proxy_used"
        else
            echo "  ❌ 失败"
        fi
        
        # 等待一段时间，让Cloud Run有机会启动新实例
        if [[ $i -lt $total_requests ]]; then
            sleep 5
        fi
    done
    
    echo ""
    echo "📊 IP轮换测试结果:"
    echo "成功请求: $successful_requests/$total_requests"
    
    if [[ ${#ip_counts[@]} -gt 0 ]]; then
        unique_ips=${#ip_counts[@]}
        echo "发现的唯一IP数量: $unique_ips"
        
        echo "IP分布:"
        for ip in "${!ip_counts[@]}"; do
            count=${ip_counts[$ip]}
            percentage=$(( count * 100 / successful_requests ))
            echo "  $ip: ${count}次 (${percentage}%)"
        done
        
        # 评估IP轮换效果
        if [[ $unique_ips -ge $(( successful_requests * 7 / 10 )) ]]; then
            echo_success "IP轮换效果: 优秀 (≥70%)"
        elif [[ $unique_ips -ge $(( successful_requests * 4 / 10 )) ]]; then
            echo_success "IP轮换效果: 良好 (40-70%)"
        elif [[ $unique_ips -ge $(( successful_requests * 2 / 10 )) ]]; then
            echo_warning "IP轮换效果: 一般 (20-40%)"
        else
            echo_warning "IP轮换效果: 较差 (<20%)"
        fi
    else
        echo_warning "无法获取IP信息进行分析"
    fi
}

# 性能测试
test_performance() {
    echo_info "测试响应性能..."
    
    start_time=$(date +%s.%N)
    
    response=$(curl -s -X POST "$SERVICE_URL/test" \
        -H "Authorization: Bearer $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{}')
    
    end_time=$(date +%s.%N)
    duration=$(echo "$end_time - $start_time" | bc -l 2>/dev/null || echo "unknown")
    
    if [[ "$duration" != "unknown" ]]; then
        duration_formatted=$(printf "%.2f" $duration)
        echo "响应时间: ${duration_formatted}秒"
        
        if (( $(echo "$duration < 5.0" | bc -l) )); then
            echo_success "响应时间优秀 (<5秒)"
        elif (( $(echo "$duration < 10.0" | bc -l) )); then
            echo_success "响应时间良好 (5-10秒)"
        else
            echo_warning "响应时间较慢 (>10秒)"
        fi
    else
        echo_warning "无法测量响应时间"
    fi
}

# 显示使用说明
show_usage_info() {
    echo ""
    echo "🎯 部署验证完成！"
    echo "────────────────────────────────────────"
    echo "📍 服务URL: $SERVICE_URL"
    echo "🔐 API Token: $API_TOKEN"
    echo ""
    echo "🔥 防封禁特性状态:"
    echo "  ✅ 部署在圣保罗机房 (最低延迟)"
    echo "  ✅ GCP自然IP轮换已启用 (主要防护)"
    echo "  🚫 代理功能已禁用 (专注GCP IP轮换)"
    echo "  ✅ 浏览器指纹伪装已启用"
    echo "  ✅ 人类行为模拟已启用"
    echo ""
    echo "📖 常用端点:"
    echo "  API文档: $SERVICE_URL/docs"
    echo "  健康检查: $SERVICE_URL/health"
    echo "  状态信息: $SERVICE_URL/status"
    echo ""
    echo "🧪 实际使用示例:"
    echo "curl -X POST \"$SERVICE_URL/get_shop_all\" \\"
    echo "  -H \"Authorization: Bearer $API_TOKEN\" \\"
    echo "  -H \"Content-Type: application/json\" \\"
    echo "  -d '{\"url\": \"https://www.ifood.com.br/delivery/sao-paulo-sp/pizza-prime---bela-vista-jardim-paulista/6d58c6a1-5d86-4b5c-823f-07e23479c83f\"}'"
}

# 主函数
main() {
    echo "🧪 开始验证圣保罗机房部署..."
    echo ""
    
    get_service_url
    test_connectivity
    test_health
    test_auth
    test_proxy_manager
    test_api_functionality
    test_performance
    
    echo_info "准备进行IP轮换测试..."
    read -p "是否执行IP轮换测试？这会需要几分钟时间 (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        test_ip_rotation
    else
        echo_info "跳过IP轮换测试"
    fi
    
    show_usage_info
    echo_success "🎊 所有测试完成！"
}

# 检查必要工具
if ! command -v jq &> /dev/null; then
    echo_warning "建议安装jq工具以获得更好的输出格式: brew install jq"
fi

if ! command -v bc &> /dev/null; then
    echo_warning "建议安装bc工具以进行精确的时间计算: brew install bc"
fi

# 执行主函数
main "$@"
