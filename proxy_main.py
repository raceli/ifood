# Cloud Functions 2nd gen 入口点
# 代理服务入口点

import asyncio
import json
from flask import Request, Response
from proxy_service import proxy_request, ProxyRequest, ProxyResponse

def run_async_function(async_func, *args, **kwargs):
    """运行异步函数的辅助函数"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(async_func(*args, **kwargs))

def proxy_endpoint_sync(request: Request):
    """同步版本的代理端点"""
    if request.method != 'POST':
        return Response('Method not allowed', status=405)
    
    try:
        request_data = request.get_json()
        if not request_data or 'url' not in request_data:
            return Response('Missing URL parameter', status=400)
        
        # 创建代理请求对象
        proxy_req = ProxyRequest(**request_data)
        
        # 执行代理请求
        result = run_async_function(proxy_request, proxy_req)
        
        # 转换为字典
        response_data = {
            "status_code": result.status_code,
            "headers": result.headers,
            "content": result.content,
            "screenshot": result.screenshot,
            "text_content": result.text_content,
            "html_content": result.html_content,
            "execution_time": result.execution_time
        }
        
        return Response(
            json.dumps(response_data, ensure_ascii=False, indent=2),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return Response(
            json.dumps({'error': str(e)}, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )

def simple_proxy_endpoint_sync(request: Request):
    """同步版本的简单代理端点"""
    if request.method != 'POST':
        return Response('Method not allowed', status=405)
    
    try:
        request_data = request.get_json()
        if not request_data or 'url' not in request_data:
            return Response('Missing URL parameter', status=400)
        
        # 创建代理请求对象
        proxy_req = ProxyRequest(**request_data)
        
        # 执行代理请求
        result = run_async_function(proxy_request, proxy_req)
        
        # 返回简化结果
        response_data = {
            "status": "success",
            "status_code": result.status_code,
            "content": result.content,
            "execution_time": result.execution_time
        }
        
        return Response(
            json.dumps(response_data, ensure_ascii=False, indent=2),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return Response(
            json.dumps({
                "status": "error",
                "error": str(e),
                "execution_time": 0
            }, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )

def health_check_sync(request: Request):
    """同步版本的健康检查端点"""
    if request.method != 'GET':
        return Response('Method not allowed', status=405)
    
    response_data = {
        "status": "healthy",
        "service": "iFood Proxy Service",
        "timestamp": asyncio.get_event_loop().time(),
        "is_cloud_function": True
    }
    
    return Response(
        json.dumps(response_data, ensure_ascii=False, indent=2),
        status=200,
        mimetype='application/json'
    )

def test_endpoint_sync(request: Request):
    """同步版本的测试端点"""
    if request.method != 'GET':
        return Response('Method not allowed', status=405)
    
    try:
        # 创建测试请求
        test_request = ProxyRequest(
            url="https://www.ifood.com.br",
            method="GET",
            timeout=30,
            extract_text=True
        )
        
        # 执行测试请求
        result = run_async_function(proxy_request, test_request)
        
        response_data = {
            "status": "success",
            "title": "iFood Proxy Service Test",
            "page_status": result.status_code,
            "content_length": len(result.content),
            "execution_time": result.execution_time,
            "text_preview": result.text_content[:200] if result.text_content else None
        }
        
        return Response(
            json.dumps(response_data, ensure_ascii=False, indent=2),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return Response(
            json.dumps({
                "status": "error",
                "error": str(e)
            }, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )

# 导出函数供 Cloud Functions 使用
__all__ = [
    'proxy_endpoint_sync', 
    'simple_proxy_endpoint_sync', 
    'health_check_sync',
    'test_endpoint_sync'
] 