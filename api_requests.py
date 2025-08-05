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
    """创建一个配置好的 requests session，模拟真实浏览器"""
    session = requests.Session()
    
    # 更真实的浏览器头部
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',  # 使用巴西葡萄牙语
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Sec-CH-UA': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"',
    }
    
    session.headers.update(headers)
    
    # 添加一些常见的 cookies
    session.cookies.update({
        'session_language': 'pt-BR',
        'country': 'BR',
        'timezone': 'America/Sao_Paulo'
    })
    
    return session

async def scrape_ifood_page_requests(target_url: str) -> Dict[str, Any]:
    """使用 requests 和 beautifulsoup4 抓取 iFood 页面"""
    try:
        session = get_session()
        logging.info(f"正在请求页面: {target_url}")
        
        # 添加随机延迟
        time.sleep(random.uniform(2, 5))
        
        # 首先访问主页建立会话
        try:
            logging.info("预访问主页建立会话...")
            home_response = session.get('https://www.ifood.com.br', timeout=15)
            logging.info(f"主页访问状态: {home_response.status_code}")
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            logging.warning(f"访问主页失败: {e}")
        
        # 设置 Referer
        session.headers.update({
            'Referer': 'https://www.ifood.com.br',
        })
        
        # 分步请求，添加更多延迟
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logging.info(f"尝试第 {attempt + 1} 次请求...")
                response = session.get(target_url, timeout=30)
                
                if response.status_code == 403:
                    logging.warning(f"收到 403 错误，尝试不同的 User-Agent...")
                    session.headers['User-Agent'] = get_random_user_agent()
                    time.sleep(random.uniform(5, 10))  # 更长的延迟
                    continue
                
                response.raise_for_status()
                break
                
            except requests.exceptions.HTTPError as e:
                if response.status_code == 403 and attempt < max_retries - 1:
                    logging.warning(f"403 错误，等待后重试...")
                    time.sleep(random.uniform(10, 20))
                    continue
                else:
                    raise e
        
        # 记录响应信息用于调试
        logging.info(f"响应状态码: {response.status_code}")
        logging.info(f"响应内容长度: {len(response.content)}")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 尝试提取店铺信息
        shop_info = {}
        
        # 提取店铺名称
        title_elem = soup.find('title')
        if title_elem:
            shop_info['name'] = title_elem.get_text().strip()
            logging.info(f"找到店铺名称: {shop_info['name']}")
        
        # 提取店铺描述
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            shop_info['description'] = meta_desc.get('content', '')
            logging.info(f"找到店铺描述: {shop_info['description'][:100]}...")
        
        # 尝试从各种元素中提取店铺信息
        # 查找所有可能的文本内容
        all_text = soup.get_text()
        logging.info(f"页面总文本长度: {len(all_text)}")
        
        # 查找所有脚本标签，可能包含JSON数据
        scripts = soup.find_all('script')
        menu_data = {
            'categories': [],
            'items': [],
            'debug_info': {
                'scripts_found': len(scripts),
                'page_title': shop_info.get('name', ''),
                'url': target_url
            }
        }
        
        # 尝试从script标签中提取JSON数据
        for script in scripts:
            if script.string:
                script_content = script.string.strip()
                # 查找可能的JSON数据
                if 'menu' in script_content.lower() or 'product' in script_content.lower() or 'item' in script_content.lower():
                    try:
                        # 尝试提取JSON
                        import json as json_lib
                        # 查找JSON模式
                        json_patterns = [
                            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                            r'window\.__APP_STATE__\s*=\s*({.*?});',
                            r'window\.initialData\s*=\s*({.*?});',
                            r'"menu":\s*(\[.*?\])',
                            r'"products":\s*(\[.*?\])',
                        ]
                        
                        for pattern in json_patterns:
                            matches = re.findall(pattern, script_content, re.DOTALL)
                            if matches:
                                try:
                                    data = json_lib.loads(matches[0])
                                    if isinstance(data, dict) and ('menu' in data or 'products' in data):
                                        menu_data['items'].append({
                                            'name': 'JSON数据提取',
                                            'description': f'从脚本中提取到数据: {str(data)[:200]}...'
                                        })
                                        logging.info(f"从脚本中提取到JSON数据")
                                        break
                                except:
                                    continue
                    except Exception as e:
                        logging.warning(f"解析脚本内容失败: {e}")
        
        # 查找可能的菜单容器（更广泛的搜索）
        menu_selectors = [
            'div[class*="menu"]',
            'div[class*="product"]',
            'div[class*="item"]',
            'div[class*="card"]',
            'section[class*="menu"]',
            'ul[class*="list"]',
            'div[data-testid*="menu"]',
            'div[data-testid*="product"]'
        ]
        
        for selector in menu_selectors:
            elements = soup.select(selector)
            if elements:
                logging.info(f"找到 {len(elements)} 个元素使用选择器: {selector}")
                for elem in elements[:5]:  # 限制数量
                    text = elem.get_text().strip()
                    if text and len(text) > 20:
                        menu_data['items'].append({
                            'name': f'元素 ({selector})',
                            'description': text[:200]
                        })
        
        # 如果没有找到具体数据，提供调试信息
        if not menu_data['items']:
            menu_data['debug_info']['sample_text'] = all_text[:500] if all_text else '无文本内容'
            menu_data['debug_info']['html_snippet'] = str(soup)[:1000] if soup else '无HTML内容'
        
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
@app.get("/test", summary="测试端点", status_code=200)
async def test_endpoint():
    """测试端点，返回基本信息"""
    return {
        "status": "运行正常",
        "version": "requests 版本",
        "message": "iFood API 服务正在运行",
        "timestamp": time.time()
    }

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