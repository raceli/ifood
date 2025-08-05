import asyncio
import logging
import random
import re
import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fake_useragent import UserAgent, FakeUserAgentError
import json
import time

# --- 配置 ---
# 从环境变量中读取API_TOKEN，如果未设置，则使用一个默认的、仅供本地测试的令牌
API_TOKEN = os.getenv("API_TOKEN", "local-dev-token")

# GCP Cloud Function 特定配置
IS_CLOUD_FUNCTION = os.getenv("FUNCTION_TARGET") is not None
GCP_REGION = os.getenv("FUNCTION_REGION", "us-central1")
USE_GCP_NATURAL_IP_ROTATION = os.getenv("USE_GCP_NATURAL_IP_ROTATION", "true").lower() == "true"

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# --- User-Agent配置 ---
try:
    ua = UserAgent(fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")
except FakeUserAgentError as e:
    logging.warning(f"fake-useragent 初始化失败: {e}. 将使用备用 User-Agent.")
    ua = None

def get_random_user_agent():
    """获取一个随机的User-Agent"""
    if ua:
        return ua.random
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"

# --- 安全认证 ---
security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """依赖项，用于验证Bearer Token"""
    if credentials.scheme != "Bearer" or credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=401, 
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# --- FastAPI 应用实例 ---
app = FastAPI(
    title="iFood Menu API (Requests Version)",
    description="一个使用 requests 和 beautifulsoup4 获取iFood店铺菜单的API服务。",
    version="1.0.0",
)

# --- 添加CORS中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 数据模型 ---
class StoreRequest(BaseModel):
    url: str

def clean_url(url: str) -> str:
    """清理URL，去掉问号后面的查询参数部分"""
    if '?' in url:
        cleaned_url = url.split('?')[0]
        logging.info(f"URL已清理: {url} -> {cleaned_url}")
        return cleaned_url
    return url

def get_session():
    """创建一个配置好的 requests session"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': get_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    return session

async def scrape_ifood_page_requests(target_url: str) -> Dict[str, Any]:
    """使用 requests 和 beautifulsoup4 抓取 iFood 页面"""
    try:
        session = get_session()
        logging.info(f"正在请求页面: {target_url}")
        
        # 添加随机延迟
        time.sleep(random.uniform(1, 3))
        
        response = session.get(target_url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 尝试提取店铺信息
        shop_info = {}
        
        # 提取店铺名称
        title_elem = soup.find('title')
        if title_elem:
            shop_info['name'] = title_elem.get_text().strip()
        
        # 提取店铺描述
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            shop_info['description'] = meta_desc.get('content', '')
        
        # 尝试从页面中提取更多信息
        # 这里可以根据实际的 iFood 页面结构进行调整
        
        # 模拟菜单数据（实际实现需要根据页面结构解析）
        menu_data = {
            'categories': [],
            'items': []
        }
        
        # 查找可能的菜单容器
        menu_containers = soup.find_all(['div', 'section'], class_=re.compile(r'menu|card|item', re.I))
        
        for container in menu_containers[:10]:  # 限制数量避免过多数据
            item_text = container.get_text().strip()
            if item_text and len(item_text) > 10:
                menu_data['items'].append({
                    'name': item_text[:100],  # 限制长度
                    'description': item_text[:200] if len(item_text) > 100 else ''
                })
        
        return {
            'shop_info': shop_info,
            'menu': menu_data,
            'url': target_url,
            'status': 'success'
        }
        
    except requests.RequestException as e:
        logging.error(f"请求失败: {e}")
        return {
            'error': 'RequestError',
            'message': f'请求页面失败: {str(e)}',
            'status': 500
        }
    except Exception as e:
        logging.error(f"抓取过程中发生错误: {e}")
        return {
            'error': 'ScrapingError',
            'message': f'抓取过程中发生错误: {str(e)}',
            'status': 500
        }

async def get_catalog_from_url_requests(target_url: str) -> Dict[str, Any]:
    """获取菜单信息（requests 版本）"""
    target_url = clean_url(target_url)
    result = await scrape_ifood_page_requests(target_url)
    return {'menu': result.get('menu', {})}

async def get_shop_info_from_url_requests(target_url: str) -> Dict[str, Any]:
    """获取店铺信息（requests 版本）"""
    target_url = clean_url(target_url)
    result = await scrape_ifood_page_requests(target_url)
    return {'shop_info': result.get('shop_info', {})}

async def get_shop_all_from_url_requests(target_url: str) -> Dict[str, Any]:
    """获取店铺全部信息（requests 版本）"""
    target_url = clean_url(target_url)
    result = await scrape_ifood_page_requests(target_url)
    return {
        'menu': result.get('menu', {}),
        'shop_info': result.get('shop_info', {})
    }

# --- API 端点 ---
@app.post("/get_menu", summary="获取iFood店铺菜单", status_code=200)
async def get_menu_endpoint_requests(request: StoreRequest, token: str = Depends(verify_token)):
    """获取iFood店铺菜单的端点（requests 版本）"""
    try:
        logging.info(f"收到菜单请求: {request.url}")
        result = await get_catalog_from_url_requests(request.url)
        return result
    except Exception as e:
        logging.error(f"处理菜单请求时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")

@app.post("/get_shop_info", summary="获取iFood店铺详情", status_code=200)
async def get_shop_info_endpoint_requests(request: StoreRequest, token: str = Depends(verify_token)):
    """获取iFood店铺详情的端点（requests 版本）"""
    try:
        logging.info(f"收到店铺信息请求: {request.url}")
        result = await get_shop_info_from_url_requests(request.url)
        return result
    except Exception as e:
        logging.error(f"处理店铺信息请求时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")

@app.post("/get_shop_all", summary="获取iFood店铺全部信息（菜单+店铺详情）", status_code=200)
async def get_shop_all_endpoint_requests(request: StoreRequest, token: str = Depends(verify_token)):
    """获取iFood店铺全部信息的端点（requests 版本）"""
    try:
        logging.info(f"收到店铺全部信息请求: {request.url}")
        result = await get_shop_all_from_url_requests(request.url)
        return result
    except Exception as e:
        logging.error(f"处理店铺全部信息请求时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080) 