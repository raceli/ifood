import asyncio
import logging
import random
import re
import os
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError
from typing import List, Optional, Dict, Any
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fake_useragent import UserAgent, FakeUserAgentError

# --- 配置 ---
PROXY_FILE = "proxies.txt"
# 从环境变量中读取API_TOKEN，如果未设置，则使用一个默认的、仅供本地测试的令牌
API_TOKEN = os.getenv("API_TOKEN", "local-dev-token")

# 云代理配置 - 从环境变量读取
CLOUD_PROXY_USERNAME = os.getenv("CLOUD_PROXY_USERNAME")
CLOUD_PROXY_PASSWORD = os.getenv("CLOUD_PROXY_PASSWORD") 
CLOUD_PROXY_HOST = os.getenv("CLOUD_PROXY_HOST")
CLOUD_PROXY_PORT = os.getenv("CLOUD_PROXY_PORT", "1080")

# 代理轮换策略
PROXY_ROTATION_STRATEGY = os.getenv("PROXY_ROTATION_STRATEGY", "random")  # random, sequential, session

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
    # If there's an issue fetching user agents (e.g., network error, outdated db),
    # fall back to a generic but modern-looking User-Agent.
    logging.warning(f"fake-useragent 初始化失败: {e}. 将使用备用 User-Agent.")
    ua = None

def get_random_user_agent():
    """获取一个随机的User-Agent，如果库初始化失败则返回一个备用值。"""
    if ua:
        return ua.random
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"

# --- 安全认证 ---
security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """依赖项，用于验证Bearer Token。"""
    if credentials.scheme != "Bearer" or credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=401, 
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# --- FastAPI 应用实例 ---
app = FastAPI(
    title="iFood Menu API",
    description="一个通过拦截网络请求来获取iFood店铺菜单的API服务。",
    version="1.0.0",
)

# --- 添加CORS中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源的跨域请求
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
)

# --- 数据模型 ---
class StoreRequest(BaseModel):
    url: str

# --- 代理处理 ---
def get_cloud_proxy_config() -> Optional[Dict[str, str]]:
    """
    获取云代理配置，支持认证。
    优先使用环境变量配置的云代理服务。
    """
    if not all([CLOUD_PROXY_USERNAME, CLOUD_PROXY_PASSWORD, CLOUD_PROXY_HOST]):
        logging.warning("云代理配置不完整，将尝试使用本地代理文件。")
        return None
    
    # 构建认证URL
    auth_url = f"http://{CLOUD_PROXY_USERNAME}:{CLOUD_PROXY_PASSWORD}@{CLOUD_PROXY_HOST}:{CLOUD_PROXY_PORT}"
    
    proxy_config = {
        "server": auth_url
    }
    logging.info(f"使用云代理: {CLOUD_PROXY_HOST}:{CLOUD_PROXY_PORT}")
    return proxy_config

def get_local_proxy_config() -> Optional[Dict[str, str]]:
    """
    从本地代理文件中读取一个随机代理并返回Playwright格式的配置字典。
    支持的格式: host:port, # 开头的行为注释。
    如果没有可用的代理，则返回None。
    """
    try:
        with open(PROXY_FILE, 'r') as f:
            proxies = [
                line.strip() for line in f 
                if line.strip() and not line.strip().startswith('#') and ':' in line
            ]
        if not proxies:
            logging.warning("代理文件中没有找到可用的代理。")
            return None
        
        chosen_proxy = random.choice(proxies)
        host, port = chosen_proxy.split(':', 1)
        
        proxy_config = {
            "server": f"socks5://{host}:{port}"
        }
        logging.info(f"已选择本地代理: {proxy_config['server']}")
        return proxy_config
    except FileNotFoundError:
        logging.warning(f"警告: 代理文件 '{PROXY_FILE}' 未找到。")
        return None
    except Exception as e:
        logging.error(f"解析本地代理时出错: {e}")
        return None

def get_gcp_natural_ip_config() -> Optional[Dict[str, str]]:
    """
    在Cloud Function环境中，利用GCP的自然IP轮换特性。
    每次函数调用都可能使用不同的出口IP。
    """
    if not IS_CLOUD_FUNCTION:
        return None
    
    if not USE_GCP_NATURAL_IP_ROTATION:
        return None
    
    logging.info(f"使用GCP自然IP轮换 (区域: {GCP_REGION})")
    # 在Cloud Function中，不设置代理配置，让GCP自动分配IP
    return None

def get_random_proxy_config() -> Optional[Dict[str, str]]:
    """
    智能代理选择策略：
    1. 在Cloud Function环境中，优先使用GCP自然IP轮换
    2. 如果配置了云代理，使用云代理
    3. 在非Cloud Function环境中，回退到本地代理文件
    4. 最后直接连接
    
    返回Playwright格式的代理配置字典。
    """
    # 1. 在Cloud Function环境中，优先使用GCP自然IP轮换
    if IS_CLOUD_FUNCTION and USE_GCP_NATURAL_IP_ROTATION:
        logging.info("在Cloud Function环境中，使用GCP自然IP轮换")
        return None  # 返回None表示不使用代理，让GCP自动分配IP
    
    # 2. 尝试云代理
    cloud_proxy = get_cloud_proxy_config()
    if cloud_proxy:
        logging.info("使用云代理配置")
        return cloud_proxy
    
    # 3. 在非Cloud Function环境中，回退到本地代理文件
    if not IS_CLOUD_FUNCTION:
        local_proxy = get_local_proxy_config()
        if local_proxy:
            logging.info("使用本地代理文件")
            return local_proxy
    
    # 4. 最终回退
    if IS_CLOUD_FUNCTION:
        logging.info("在Cloud Function环境中，将使用GCP分配的动态IP")
    else:
        logging.warning("未找到可用的代理配置，将直接连接。")
    
    return None

def clean_url(url: str) -> str:
    """
    清理URL，去掉问号后面的查询参数部分。
    
    Args:
        url: 原始URL
        
    Returns:
        清理后的URL，不包含查询参数
    """
    if '?' in url:
        cleaned_url = url.split('?')[0]
        logging.info(f"URL已清理: {url} -> {cleaned_url}")
        return cleaned_url
    return url

# --- 核心抓取逻辑 (重构后) ---

async def _process_api_response(key: str, response: Any) -> Dict[str, Any]:
    """
    处理单个从 Playwright 拦截到的响应，将其转换为JSON或错误字典。
    """
    if isinstance(response, Exception):
        return {"error": "ResponseError", "message": f"获取 {key} 信息失败: {type(response).__name__}"}
    if response is None:
        return {"error": "ResponseMissing", "message": f"未捕获到 {key} API响应"}

    logging.info(f"成功拦截到 {key} API 请求: {response.url} [状态: {response.status}]")
    if response.status == 403:
        return {"error": "Forbidden", "message": f"代理IP在获取 {key} 时被封禁或拒绝访问。", "status": 403}
    if response.ok:
        return await response.json()
    else:
        return {"error": "APIError", "message": f"{key} API返回错误状态: {response.status}", "status": response.status}

async def _scrape_ifood_page(
    target_url: str,
    proxy_config: Optional[Dict[str, str]],
    api_patterns: Dict[str, re.Pattern]
) -> Dict[str, Any]:
    """
    一个通用的抓取函数，处理浏览器生命周期、拦截API请求并返回处理后的JSON数据。
    针对Cloud Function环境进行了优化。
    """
    async with async_playwright() as p:
        browser = None
        try:
            # Cloud Function 优化的启动选项
            launch_options = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=TranslateUI",
                    "--disable-ipc-flooding-protection",
                ]
            }
            
            # 在Cloud Function环境中，添加更多优化选项
            if IS_CLOUD_FUNCTION:
                launch_options["args"].extend([
                    "--single-process",  # 单进程模式，节省内存
                    "--disable-extensions",
                    "--disable-plugins",
                    "--disable-images",  # 禁用图片加载，提高速度
                    "--disable-javascript",  # 禁用JS，只保留必要的
                ])
            
            if proxy_config:
                launch_options["proxy"] = proxy_config
                logging.info("正在通过代理启动浏览器...")
            else:
                if IS_CLOUD_FUNCTION:
                    logging.info("在Cloud Function环境中，使用GCP动态IP启动浏览器...")
                else:
                    logging.info("未提供代理，正在直接启动浏览器...")
            
            # 在 Cloud Function 环境中，尝试使用系统 Chromium 或自动安装
            if IS_CLOUD_FUNCTION:
                try:
                    # 首先尝试使用系统安装的 Chromium
                    browser = await p.chromium.launch(**launch_options)
                    logging.info("成功使用系统 Chromium 启动浏览器")
                except Exception as e:
                    logging.warning(f"系统 Chromium 启动失败: {e}")
                    # 如果失败，尝试自动安装 Playwright 浏览器
                    try:
                        import subprocess
                        import sys
                        logging.info("正在安装 Playwright 浏览器...")
                        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], 
                                     check=True, capture_output=True)
                        logging.info("Playwright 浏览器安装完成，重新启动...")
                        browser = await p.chromium.launch(**launch_options)
                    except Exception as install_error:
                        logging.error(f"Playwright 浏览器安装失败: {install_error}")
                        # 最后尝试使用 firefox 作为备选
                        logging.info("尝试使用 Firefox 作为备选浏览器...")
                        browser = await p.firefox.launch(headless=True)
            else:
                browser = await p.chromium.launch(**launch_options)
            
            user_agent_str = get_random_user_agent()
            logging.info(f"使用 User-Agent: {user_agent_str}")
            page = await browser.new_page(user_agent=user_agent_str)
            
            logging.info(f"正在导航到: {target_url}")

            response_awaitables = [
                page.wait_for_event(
                    "response",
                    lambda res, p=pattern: p.search(res.url),
                    timeout=25000
                )
                for pattern in api_patterns.values()
            ]
            navigation_awaitable = page.goto(target_url, wait_until='domcontentloaded', timeout=15000)
            
            all_results = await asyncio.gather(
                *response_awaitables, navigation_awaitable, return_exceptions=True
            )
            
            # 【修复】增加明确的日志记录，以解释为何失败
            # 1. 检查导航任务本身是否失败
            navigation_result = all_results[-1]
            if isinstance(navigation_result, Exception):
                logging.error(f"页面导航或主任务失败: {type(navigation_result).__name__} - {navigation_result}")

            # 2. 检查各个API响应的等待任务是否失败
            response_results = all_results[:-1]
            api_keys = list(api_patterns.keys())
            for i, res in enumerate(response_results):
                if isinstance(res, Exception):
                    logging.error(f"等待 API '{api_keys[i]}' 响应时失败: {type(res).__name__}")
            
            scraped_responses = dict(zip(api_keys, response_results))

            # 在浏览器关闭前处理所有响应
            processing_tasks = [
                _process_api_response(key, response)
                for key, response in scraped_responses.items()
            ]
            processed_results_list = await asyncio.gather(*processing_tasks)
            
            return dict(zip(api_keys, processed_results_list))

        except Exception as e:
            error_message = str(e)
            if isinstance(e, TimeoutError):
                error_message = "操作超时。可能原因：页面加载过慢、未触发API请求、或被CAPTCHA阻挡。"
            logging.error(f"抓取过程中发生错误: {error_message}")
            return {
                key: {"error": type(e).__name__, "message": error_message, "status": 500}
                for key in api_patterns.keys()
            }
        finally:
            if browser and browser.is_connected():
                await browser.close()
                logging.info("浏览器已关闭。")

async def get_catalog_from_url(target_url: str, proxy_config: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """
    使用重构后的抓取逻辑访问iFood页面，并仅拦截菜单目录API的响应。
    """
    api_patterns = {"menu": re.compile(r"merchants/.*/catalog")}
    return await _scrape_ifood_page(target_url, proxy_config, api_patterns)

async def get_shop_info_from_url(target_url: str, proxy_config: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """
    使用重构后的抓取逻辑访问iFood页面，并仅拦截商户信息API的响应。
    """
    api_patterns = {"shop_info": re.compile(r"merchant-info/graphql")}
    return await _scrape_ifood_page(target_url, proxy_config, api_patterns)

async def get_shop_all_from_url(target_url: str, proxy_config: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """
    使用重构后的抓取逻辑访问iFood页面，并同时拦截菜单目录API和商户信息API的响应。
    """
    api_patterns = {
        "menu": re.compile(r"merchants/.*/catalog"),
        "shop_info": re.compile(r"merchant-info/graphql")
    }
    return await _scrape_ifood_page(target_url, proxy_config, api_patterns)

# --- API 端点 ---
@app.post("/get_menu", summary="获取iFood店铺菜单", status_code=200)
async def get_menu_endpoint(request: StoreRequest, token: str = Depends(verify_token)):
    """
    接收一个iFood店铺的web URL，返回其菜单的JSON数据。

    - **url**: iFood店铺的完整URL。
    - **需要认证**: 请求头中必须包含 'Authorization: Bearer your-super-secret-token'。
    """
    proxy_config = get_random_proxy_config()
    
    # 清理URL，去掉查询参数
    cleaned_url = clean_url(request.url)

    logging.info(f"开始为URL处理请求: {cleaned_url}")
    result = await get_catalog_from_url(cleaned_url, proxy_config)

    if "error" in result.get("menu", {}):
        status_code = result["menu"].get("status", 500)
        raise HTTPException(status_code=status_code, detail=result)
    
    return result

@app.post("/get_shop_info", summary="获取iFood店铺详情", status_code=200)
async def get_shop_info_endpoint(request: StoreRequest, token: str = Depends(verify_token)):
    """
    接收一个iFood店铺的web URL，仅返回其店铺的详细信息。

    - **url**: iFood店铺的完整URL。
    - **需要认证**: 请求头中必须包含 'Authorization: Bearer your-super-secret-token'。
    """
    proxy_config = get_random_proxy_config()
    
    # 清理URL，去掉查询参数
    cleaned_url = clean_url(request.url)

    logging.info(f"开始为URL处理请求（仅店铺信息）: {cleaned_url}")
    result = await get_shop_info_from_url(cleaned_url, proxy_config)

    if "error" in result.get("shop_info", {}):
        status_code = result["shop_info"].get("status", 500)
        raise HTTPException(status_code=status_code, detail=result)
    
    return result

@app.post("/get_shop_all", summary="获取iFood店铺全部信息（菜单+店铺详情）", status_code=200)
async def get_shop_all_endpoint(request: StoreRequest, token: str = Depends(verify_token)):
    """
    接收一个iFood店铺的web URL，返回其菜单和店铺信息的JSON数据。

    - **url**: iFood店铺的完整URL。
    - **需要认证**: 请求头中必须包含 'Authorization: Bearer your-super-secret-token'。
    """
    proxy_config = get_random_proxy_config()
    
    # 清理URL，去掉查询参数
    cleaned_url = clean_url(request.url)

    logging.info(f"开始为URL处理请求（全信息）: {cleaned_url}")
    result = await get_shop_all_from_url(cleaned_url, proxy_config)

    # 检查是否所有子任务都失败了
    all_failed = all("error" in v for v in result.values())
    if all_failed and result:
        any_error = next(iter(result.values()))
        status_code = any_error.get("status", 500)
        raise HTTPException(status_code=status_code, detail=result)

    return result

# --- 如何运行 ---
# 1. 确保 'proxies.txt' 文件存在且包含有效的SOCKS5代理。
# 2. 安装依赖: pip install -r requirements.txt
# 3. 运行Playwright的浏览器安装: playwright install
# 4. 启动服务器: uvicorn api:app --reload
# 5. 在 http://127.0.0.1:8000/docs 查看API文档并测试。
