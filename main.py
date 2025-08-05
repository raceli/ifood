# Cloud Functions 2nd gen 入口点
# 这个文件是 Google Cloud Functions 的必需入口点

import asyncio
import json
from flask import Request, Response
from api_requests import get_menu_endpoint_requests, get_shop_info_endpoint_requests, get_shop_all_endpoint_requests, StoreRequest

def run_async_function(async_func, *args, **kwargs):
    """运行异步函数的辅助函数"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(async_func(*args, **kwargs))

def get_menu_endpoint_sync(request: Request):
    """同步版本的菜单端点（requests 版本）"""
    if request.method != 'POST':
        return Response('Method not allowed', status=405)
    
    try:
        request_data = request.get_json()
        if not request_data or 'url' not in request_data:
            return Response('Missing URL parameter', status=400)
        
        store_request = StoreRequest(url=request_data['url'])
        result = run_async_function(get_menu_endpoint_requests, store_request, None)
        
        return Response(
            json.dumps(result, ensure_ascii=False, indent=2),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return Response(
            json.dumps({'error': str(e)}, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )

def get_shop_info_endpoint_sync(request: Request):
    """同步版本的店铺信息端点（requests 版本）"""
    if request.method != 'POST':
        return Response('Method not allowed', status=405)
    
    try:
        request_data = request.get_json()
        if not request_data or 'url' not in request_data:
            return Response('Missing URL parameter', status=400)
        
        store_request = StoreRequest(url=request_data['url'])
        result = run_async_function(get_shop_info_endpoint_requests, store_request, None)
        
        return Response(
            json.dumps(result, ensure_ascii=False, indent=2),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return Response(
            json.dumps({'error': str(e)}, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )

def get_shop_all_endpoint_sync(request: Request):
    """同步版本的店铺全部信息端点（requests 版本）"""
    if request.method != 'POST':
        return Response('Method not allowed', status=405)
    
    try:
        request_data = request.get_json()
        if not request_data or 'url' not in request_data:
            return Response('Missing URL parameter', status=400)
        
        store_request = StoreRequest(url=request_data['url'])
        result = run_async_function(get_shop_all_endpoint_requests, store_request, None)
        
        return Response(
            json.dumps(result, ensure_ascii=False, indent=2),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return Response(
            json.dumps({'error': str(e)}, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )

# 导出函数供 Cloud Functions 使用
__all__ = ['get_menu_endpoint_sync', 'get_shop_info_endpoint_sync', 'get_shop_all_endpoint_sync'] 