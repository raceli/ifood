import asyncio
import logging
import random
import re
import os
import time
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError
from typing import List, Optional, Dict, Any
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fake_useragent import UserAgent, FakeUserAgentError
from stealth_config import (
    get_stealth_browser_args, 
    get_random_stealth_config, 
    get_stealth_page_scripts,
    get_realistic_headers,
    get_human_like_delay
)
from proxy_manager import get_smart_proxy_config, record_proxy_result, proxy_manager

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
DISABLE_PROXY = os.getenv("DISABLE_PROXY", "false").lower() == "true"  # 是否禁用代理

# GCP Cloud Function/Cloud Run 特定配置
IS_CLOUD_FUNCTION = os.getenv("FUNCTION_TARGET") is not None
IS_CLOUD_RUN = os.getenv("K_SERVICE") is not None  # Cloud Run 环境变量
GCP_REGION = os.getenv("FUNCTION_REGION", "us-central1")
USE_GCP_NATURAL_IP_ROTATION = os.getenv("USE_GCP_NATURAL_IP_ROTATION", "true").lower() == "true"

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 创建自定义日志记录器
logger = logging.getLogger("ifood_api")
logger.setLevel(logging.INFO)

# 添加控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 在 Cloud Function 环境中添加文件日志
if IS_CLOUD_FUNCTION:
    try:
        file_handler = logging.FileHandler("/tmp/ifood_api.log")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info("已启用文件日志记录")
    except Exception as e:
        logger.warning(f"无法创建文件日志处理器: {e}")

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

# --- 全局异常处理器 ---
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理器，统一处理未捕获的异常"""
    logger.error(f"未捕获的异常: {type(exc).__name__} - {str(exc)}", exc_info=True)
    
    return {
        "error": "InternalServerError",
        "message": "服务器内部错误",
        "detail": str(exc) if not IS_CLOUD_FUNCTION else "请查看服务器日志",
        "timestamp": asyncio.get_event_loop().time()
    }

@app.exception_handler(TimeoutError)
async def timeout_exception_handler(request, exc):
    """超时异常处理器"""
    logger.warning(f"请求超时: {str(exc)}")
    
    return {
        "error": "TimeoutError", 
        "message": "请求超时，请稍后重试",
        "detail": str(exc),
        "timestamp": asyncio.get_event_loop().time()
    }

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
    增强的智能代理选择策略：
    1. 如果禁用代理，直接返回None
    2. 在Cloud Function环境中，优先使用GCP自然IP轮换
    3. 使用智能代理管理器选择最佳代理
    4. 如果配置了云代理，使用云代理
    5. 最后直接连接
    
    返回Playwright格式的代理配置字典。
    """
    # 0. 检查是否禁用代理
    if DISABLE_PROXY:
        logging.info("代理功能已禁用，将使用GCP自然IP轮换")
        return None
    
    # 1. 在Cloud Function环境中，强制使用GCP自然IP轮换，不使用任何代理
    if IS_CLOUD_FUNCTION:
        logging.info("在Cloud Function环境中，强制使用GCP自然IP轮换，不使用代理")
        return None  # 返回None表示不使用代理，让GCP自动分配IP
    
    # 2. 优先使用智能代理管理器（仅在非Cloud Function环境中）
    smart_proxy = get_smart_proxy_config()
    if smart_proxy:
        logging.info(f"使用智能代理管理器选择的代理: {smart_proxy.get('server', 'unknown')}")
        return smart_proxy
    
    # 3. 回退到云代理（仅在非Cloud Function环境中）
    cloud_proxy = get_cloud_proxy_config()
    if cloud_proxy:
        logging.info("使用云代理配置")
        return cloud_proxy
    
    # 4. 最终回退
    logging.info("未找到可用的代理配置，将直接连接。")
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

def _get_optimized_browser_args() -> List[str]:
    """
    获取增强的反检测浏览器启动参数
    结合了Browserless最佳实践和高级反检测技术
    """
    # 使用新的隐身配置
    base_args = get_stealth_browser_args()
    
    # 在 Cloud Function 环境中进一步优化
    if IS_CLOUD_FUNCTION or IS_CLOUD_RUN:
        base_args.extend([
            "--single-process",  # 减少内存占用
            "--disable-images",  # 禁用图片加载
            "--disable-site-isolation-trials",
            "--disable-speech-api",
            "--metrics-recording-only",
            "--safebrowsing-disable-auto-update",
        ])
        
        # 设置适合云环境的窗口大小
        base_args.append("--window-size=1366,768")
    
    return base_args

async def _launch_browser_with_fallback(playwright_instance, launch_options: Dict[str, Any]):
    """
    使用后备策略启动浏览器，参考 Browserless 建议的错误处理方式。
    """
    strategies = [
        {
            "name": "标准启动",
            "options": launch_options
        },
        {
            "name": "最小化启动", 
            "options": {
                **launch_options,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process"
                ]
            }
        },
        {
            "name": "无头浏览器启动",
            "options": {
                **launch_options,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                    "--disable-extensions",
                    "--disable-plugins",
                    "--disable-images",
                    "--disable-javascript",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor"
                ]
            }
        }
    ]
    
    if IS_CLOUD_FUNCTION:
        # Cloud Function 环境的特殊策略
        strategies.append({
            "name": "Cloud Function 浏览器启动",
            "options": {
                **launch_options,
                "executable_path": "/www-data-home/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage", 
                    "--disable-gpu",
                    "--single-process"
                ]
            }
        })
        
        # 尝试使用系统 Chrome (如果存在)
        strategies.append({
            "name": "系统 Chrome 启动",
            "options": {
                **launch_options,
                "executable_path": "/usr/bin/google-chrome-stable",
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox", 
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--headless"
                ]
            }
        })
        
        # 尝试使用系统 Chromium (如果存在)
        strategies.append({
            "name": "系统 Chromium 启动",
            "options": {
                **launch_options,
                "executable_path": "/usr/bin/chromium-browser",
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox", 
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--headless"
                ]
            }
        })
        
        # 尝试使用系统 Chrome (备用路径)
        strategies.append({
            "name": "系统 Chrome 备用启动",
            "options": {
                **launch_options,
                "executable_path": "/usr/bin/chromium",
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox", 
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--headless"
                ]
            }
        })
        
        strategies.append({
            "name": "系统浏览器查找启动",
            "options": None  # 特殊标记
        })
        
        strategies.append({
            "name": "Cloud Function 环境安装",
            "options": None  # 特殊标记
        })
        
        strategies.append({
            "name": "动态安装后启动",
            "options": None  # 特殊标记
        })
    
    last_error = None
    
    for strategy in strategies:
        try:
            logging.info(f"尝试{strategy['name']}...")
            
            if strategy["name"] == "系统浏览器查找启动":
                # 动态查找系统中可用的浏览器
                import subprocess
                import os
                logging.info("正在查找系统中可用的浏览器...")
                
                # 可能的浏览器路径
                possible_browsers = [
                    "/usr/bin/google-chrome-stable",
                    "/usr/bin/chromium-browser", 
                    "/usr/bin/chromium",
                    "/usr/bin/google-chrome",
                    "/usr/bin/chrome",
                    "/snap/bin/chromium",
                    "/opt/google/chrome/chrome"
                ]
                
                found_browser = None
                for browser_path in possible_browsers:
                    if os.path.exists(browser_path):
                        found_browser = browser_path
                        logging.info(f"找到系统浏览器: {found_browser}")
                        break
                
                if found_browser:
                    browser = await playwright_instance.chromium.launch(
                        headless=True,
                        timeout=30000,
                        executable_path=found_browser,
                        args=[
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage", 
                            "--disable-gpu",
                            "--single-process"
                        ]
                    )
                else:
                    # 尝试使用 which 命令查找
                    try:
                        result = subprocess.run(
                            ["which", "chromium-browser"], 
                            capture_output=True, 
                            text=True,
                            timeout=10
                        )
                        if result.returncode == 0:
                            found_browser = result.stdout.strip()
                            logging.info(f"通过 which 找到浏览器: {found_browser}")
                            
                            browser = await playwright_instance.chromium.launch(
                                headless=True,
                                timeout=30000,
                                executable_path=found_browser,
                                args=[
                                    "--no-sandbox",
                                    "--disable-setuid-sandbox",
                                    "--disable-dev-shm-usage", 
                                    "--disable-gpu",
                                    "--single-process"
                                ]
                            )
                        else:
                            raise Exception("未找到任何系统浏览器")
                    except Exception as e:
                        logging.error(f"查找系统浏览器失败: {e}")
                        raise Exception("未找到任何系统浏览器")
                        
            elif strategy["name"] == "Cloud Function 环境安装":
                # Cloud Function 环境中的浏览器安装
                import subprocess
                import sys
                import os
                logging.info("在 Cloud Function 环境中安装 Playwright 浏览器...")
                
                try:
                    # 设置浏览器路径环境变量
                    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '/www-data-home/.cache/ms-playwright'
                    
                    # 创建目录
                    os.makedirs('/www-data-home/.cache/ms-playwright', exist_ok=True)
                    
                    # 安装浏览器
                    result = subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"], 
                        capture_output=True, 
                        text=True,
                        timeout=300,
                        env={**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': '/www-data-home/.cache/ms-playwright'}
                    )
                    
                    if result.returncode != 0:
                        logging.warning(f"Cloud Function 环境安装失败: {result.stderr}")
                        raise Exception(f"安装失败: {result.stderr}")
                    
                    logging.info("Cloud Function 环境 Chromium 安装完成...")
                    
                    # 查找安装的浏览器
                    import glob
                    browser_paths = glob.glob('/www-data-home/.cache/ms-playwright/chromium-*/chrome-linux/chrome')
                    
                    if browser_paths:
                        actual_browser_path = browser_paths[0]
                        logging.info(f"找到浏览器路径: {actual_browser_path}")
                        
                        browser = await playwright_instance.chromium.launch(
                            headless=True,
                            timeout=30000,
                            executable_path=actual_browser_path,
                            args=[
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage", 
                                "--disable-gpu",
                                "--single-process"
                            ]
                        )
                    else:
                        raise Exception("未找到安装的浏览器")
                        
                except Exception as install_error:
                    logging.error(f"Cloud Function 环境安装失败: {install_error}")
                    raise install_error
                    
            elif strategy["name"] == "动态安装后启动":
                # 动态安装浏览器 (参考 GitHub issue #1491)
                import subprocess
                import sys
                import os
                logging.info("正在动态安装 Playwright 浏览器...")
                
                try:
                    # 设置浏览器路径环境变量
                    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '/tmp/ms-playwright'
                    
                    # 创建临时目录
                    os.makedirs('/tmp/ms-playwright', exist_ok=True)
                    
                    # 安装浏览器到临时目录
                    result = subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"], 
                        capture_output=True, 
                        text=True,
                        timeout=300,
                        env={**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': '/tmp/ms-playwright'}
                    )
                    
                    if result.returncode != 0:
                        logging.warning(f"Playwright 安装失败: {result.stderr}")
                        raise Exception(f"安装失败: {result.stderr}")
                    
                    logging.info("Chromium 安装完成，重新启动...")
                    
                    # 查找安装的浏览器
                    import glob
                    browser_paths = glob.glob('/tmp/ms-playwright/chromium-*/chrome-linux/chrome')
                    
                    if browser_paths:
                        actual_browser_path = browser_paths[0]
                        logging.info(f"找到浏览器路径: {actual_browser_path}")
                        
                        browser = await playwright_instance.chromium.launch(
                            headless=True,
                            timeout=30000,
                            executable_path=actual_browser_path,
                            args=[
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage", 
                                "--disable-gpu",
                                "--single-process"
                            ]
                        )
                    else:
                        raise Exception("未找到安装的浏览器")
                        
                except Exception as install_error:
                    logging.error(f"动态安装失败: {install_error}")
                    raise install_error
            else:
                if strategy["name"] == "Cloud Function 浏览器启动":
                    # 处理通配符路径
                    import glob
                    import os
                    
                    # 尝试多个可能的浏览器路径
                    possible_paths = [
                        "/www-data-home/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
                        "/root/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
                        "/tmp/ms-playwright/chromium-*/chrome-linux/chrome",
                        "/app/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
                        "/home/www-data/.cache/ms-playwright/chromium-*/chrome-linux/chrome"
                    ]
                    
                    browser_paths = []
                    for pattern in possible_paths:
                        browser_paths = glob.glob(pattern)
                        if browser_paths:
                            logging.info(f"在路径 {pattern} 找到浏览器")
                            break
                    
                    if browser_paths:
                        actual_browser_path = browser_paths[0]
                        logging.info(f"找到浏览器路径: {actual_browser_path}")
                        
                        browser_options = strategy["options"].copy()
                        browser_options["executable_path"] = actual_browser_path
                        browser = await playwright_instance.chromium.launch(**browser_options)
                    else:
                        # 如果找不到浏览器，尝试列出目录内容进行调试
                        logging.error("未找到浏览器，尝试列出可能的目录:")
                        for path in ["/www-data-home/.cache", "/root/.cache", "/tmp", "/app/.cache", "/home/www-data/.cache"]:
                            try:
                                if os.path.exists(path):
                                    logging.error(f"目录 {path} 存在，内容: {os.listdir(path)}")
                                else:
                                    logging.error(f"目录 {path} 不存在")
                            except Exception as e:
                                logging.error(f"无法访问目录 {path}: {e}")
                        
                        raise Exception(f"未找到浏览器，已尝试所有可能的路径")
                else:
                    browser = await playwright_instance.chromium.launch(**strategy["options"])
            
            logging.info(f"{strategy['name']}成功")
            return browser
            
        except Exception as e:
            last_error = e
            logging.warning(f"{strategy['name']}失败: {str(e)}")
            continue
    
    # 所有策略都失败了
    raise Exception(f"无法启动浏览器，最后错误: {str(last_error)}")

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
        try:
            json_data = await response.json()
            
            # 为catalog/menu数据添加详细日志
            if key == "menu" and isinstance(json_data, dict):
                logging.info(f"=== CATALOG/MENU API 响应详情 ===")
                logging.info(f"响应URL: {response.url}")
                logging.info(f"响应状态: {response.status}")
                logging.info(f"响应头: {dict(response.headers)}")
                
                # 记录catalog数据结构
                if "categories" in json_data:
                    categories_count = len(json_data["categories"])
                    logging.info(f"分类数量: {categories_count}")
                    
                    for i, category in enumerate(json_data["categories"]):
                        if isinstance(category, dict):
                            category_name = category.get("name", "未知分类")
                            items_count = len(category.get("items", []))
                            logging.info(f"  分类 {i+1}: {category_name} - 商品数量: {items_count}")
                            
                            # 记录前几个商品的信息
                            items = category.get("items", [])
                            for j, item in enumerate(items[:3]):  # 只记录前3个商品
                                if isinstance(item, dict):
                                    item_name = item.get("name", "未知商品")
                                    item_price = item.get("price", "无价格")
                                    logging.info(f"    商品 {j+1}: {item_name} - 价格: {item_price}")
                            
                            if len(items) > 3:
                                logging.info(f"    ... 还有 {len(items) - 3} 个商品")
                        else:
                            logging.warning(f"  分类 {i+1} 格式异常: {type(category)}")
                
                # 记录其他重要字段
                for field in ["merchantId", "merchantName", "totalItems", "totalCategories"]:
                    if field in json_data:
                        logging.info(f"{field}: {json_data[field]}")
                
                logging.info(f"=== CATALOG/MENU API 响应详情结束 ===")
            else:
                logging.info(f"{key} API 响应数据: {json_data}")
            
            return json_data
        except Exception as json_error:
            logging.error(f"解析 {key} API JSON响应时出错: {str(json_error)}")
            # 尝试获取原始文本内容
            try:
                raw_text = await response.text()
                logging.info(f"{key} API 原始响应内容 (前500字符): {raw_text[:500]}")
                return {"error": "JSONParseError", "message": f"JSON解析失败: {str(json_error)}", "raw_content": raw_text[:1000]}
            except Exception as text_error:
                logging.error(f"获取 {key} API 原始响应内容时出错: {str(text_error)}")
                return {"error": "ResponseParseError", "message": f"无法解析响应: {str(json_error)}"}
    else:
        return {"error": "APIError", "message": f"{key} API返回错误状态: {response.status}", "status": response.status}

async def _scrape_ifood_page(
    target_url: str,
    proxy_config: Optional[Dict[str, str]],
    api_patterns: Dict[str, re.Pattern]
) -> Dict[str, Any]:
    """
    一个通用的抓取函数，处理浏览器生命周期、拦截API请求并返回处理后的JSON数据。
    针对Cloud Function环境进行了优化，参考 Browserless 最佳实践。
    """
    async with async_playwright() as p:
        browser = None
        try:
            # 根据环境变量获取超时配置
            browser_timeout = int(os.getenv("BROWSER_TIMEOUT", "60")) * 1000  # 默认60秒
            request_timeout = int(os.getenv("REQUEST_TIMEOUT", "90")) * 1000  # 默认90秒
            
            # 根据 Browserless 建议，为 Cloud Function 优化启动配置
            launch_options = {
                "headless": True,
                "timeout": browser_timeout,  # 使用环境变量配置的启动超时
                "args": _get_optimized_browser_args()
            }
            
            # 添加代理配置
            if proxy_config:
                launch_options["proxy"] = proxy_config
                logging.info("正在通过代理启动浏览器...")
            else:
                if IS_CLOUD_FUNCTION:
                    logging.info("在Cloud Function环境中，使用GCP动态IP启动浏览器...")
                else:
                    logging.info("未提供代理，正在直接启动浏览器...")
            
            # 统一的浏览器启动逻辑
            browser = await _launch_browser_with_fallback(p, launch_options)
            
            # 获取随机隐身配置
            stealth_config = get_random_stealth_config()
            
            # 创建页面并设置增强的反检测配置
            logging.info(f"使用隐身配置: {stealth_config.user_agent[:50]}...")
            
            page = await browser.new_page(
                user_agent=stealth_config.user_agent,
                viewport={"width": stealth_config.viewport_width, "height": stealth_config.viewport_height},
                extra_http_headers=get_realistic_headers()
            )
            
            # 设置地理位置权限和坐标（在上下文级别）
            context = page.context
            await context.grant_permissions(['geolocation'])
            logging.info("设置地理位置为圣保罗...")
            await context.set_geolocation({"latitude": -23.5505, "longitude": -46.6333})  # 圣保罗坐标
            
            # 注入反检测脚本
            for script in get_stealth_page_scripts():
                await page.add_init_script(script)
            
            # 注入地理位置模拟脚本
            geolocation_script = """
                // 覆盖地理位置API，强制返回圣保罗坐标
                Object.defineProperty(navigator.geolocation, 'getCurrentPosition', {
                    value: function(success, error, options) {
                        const position = {
                            coords: {
                                latitude: -23.5505,
                                longitude: -46.6333,
                                accuracy: 10,
                                altitude: null,
                                altitudeAccuracy: null,
                                heading: null,
                                speed: null
                            },
                            timestamp: Date.now()
                        };
                        if (success) {
                            success(position);
                        }
                    }
                });
                
                Object.defineProperty(navigator.geolocation, 'watchPosition', {
                    value: function(success, error, options) {
                        const position = {
                            coords: {
                                latitude: -23.5505,
                                longitude: -46.6333,
                                accuracy: 10,
                                altitude: null,
                                altitudeAccuracy: null,
                                heading: null,
                                speed: null
                            },
                            timestamp: Date.now()
                        };
                        if (success) {
                            success(position);
                        }
                        return 1; // 返回watchId
                    }
                });
            """
            await page.add_init_script(geolocation_script)
            
            # 设置页面超时和错误处理
            page.set_default_navigation_timeout(request_timeout)  # 使用环境变量配置的导航超时
            page.set_default_timeout(request_timeout)  # 使用环境变量配置的默认超时
            
            # 拦截并修改API请求，强制添加地理位置参数
            async def handle_api_request(route):
                request = route.request
                url = request.url
                
                # 检查是否是需要阻断的资源（图片、CSS等）
                if IS_CLOUD_FUNCTION and any(ext in url.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.css']):
                    await route.abort()
                    return
                
                # 如果是iFood的API请求，记录详细信息并修改
                if "cw-marketplace.ifood.com.br" in url or "merchant-info/graphql" in url:
                    # 记录原始请求详情
                    logging.info(f"📡 拦截到iFood API请求:")
                    logging.info(f"  URL: {url}")
                    logging.info(f"  方法: {request.method}")
                    logging.info(f"  请求头: {dict(request.headers)}")
                    if request.post_data:
                        logging.info(f"  POST数据: {request.post_data}")
                    
                    # 准备修改后的URL和请求头
                    modified_url = url
                    if "latitude=&" in url or "longitude=&" in url:
                        modified_url = url.replace("latitude=&longitude=", "latitude=-23.5505&longitude=-46.6333")
                        logging.info(f"🔧 修改API请求URL: {url} -> {modified_url}")
                    
                    # 添加关键的iFood请求头
                    import uuid
                    import time
                    
                    additional_headers = {
                        'X-Ifood-Session-Id': str(uuid.uuid4()),
                        'X-Ifood-Device-Id': str(uuid.uuid4()),
                        'x-client-application-key': '41a266ee-51b7-4c37-9e9d-5cd331f280d5',
                        'platform': 'Desktop',
                        'app_version': '9.126.0',
                        'browser': 'Mac OS',
                        'x-device-model': 'Macintosh Chrome',
                        'Accept': 'application/json, text/plain, */*',
                        'Content-Type': 'application/json',
                        'Referer': 'https://www.ifood.com.br/',
                        'Origin': 'https://www.ifood.com.br'
                    }
                    
                    # 检查并处理cookies
                    try:
                        existing_cookie = request.headers.get('cookie', '')
                        if existing_cookie:
                            logging.info(f"🍪 现有Cookie头: {existing_cookie[:200]}...")
                            # 检查是否包含PX相关cookies
                            if '_px' in existing_cookie or 'pxcts' in existing_cookie:
                                logging.info("✅ 检测到PX相关cookies在请求中")
                            else:
                                logging.warning("⚠️ 请求中缺少PX相关cookies")
                        else:
                            logging.warning("⚠️ 请求中完全缺少Cookie头，可能导致403错误")
                            
                            # 尝试从页面上下文获取cookies并添加到请求中
                            # 注意：这是一个尝试性的修复，可能需要进一步调整
                            logging.info("尝试从页面上下文获取cookies...")
                    except Exception as e:
                        logging.warning(f"检查Cookie时出错: {e}")
                    
                    logging.info(f"🔧 添加关键请求头: {additional_headers}")
                    
                    # 继续请求并添加请求头
                    await route.continue_(url=modified_url, headers={**dict(request.headers), **additional_headers})
                else:
                    # 正常继续请求
                    await route.continue_()
            
            # 应用统一的请求拦截器
            await page.route("**/*", handle_api_request)
            
            # 设置更宽松的网络策略，减少超时，并添加iFood特定的请求头
            await page.set_extra_http_headers({
                'Accept-Language': 'pt-BR,pt;q=1',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Cache-Control': 'no-cache, no-store',
                'Pragma': 'no-cache',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'Referer': 'https://www.ifood.com.br/',
                'platform': 'Desktop',
                'app_version': '9.126.0',
                'browser': 'Mac OS',
                'x-device-model': 'Macintosh Chrome',
                'Origin': 'https://www.ifood.com.br',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            })
            
            logging.info(f"正在导航到: {target_url}")

            # 记录开始时间（用于计算响应时间）
            start_time = time.time()

            # 先导航到页面，确保完全渲染
            logging.info("导航到页面并等待完全渲染...")
            await page.goto(target_url, wait_until='networkidle', timeout=request_timeout)
            
            # 等待页面完全加载，包括所有JavaScript
            logging.info("等待页面完全加载和JavaScript执行...")
            await page.wait_for_timeout(8000)  # 增加到8秒
            
            # 等待关键元素出现，确保页面渲染完成
            try:
                logging.info("等待关键页面元素出现...")
                await page.wait_for_selector('body', timeout=10000)
                await page.wait_for_function('document.readyState === "complete"', timeout=10000)
                logging.info("页面渲染状态检查完成")
            except Exception as e:
                logging.warning(f"等待页面元素时出错: {e}")
            
            # 模拟真实用户行为
            logging.info("模拟真实用户行为...")
            try:
                # 滚动页面
                await page.evaluate('window.scrollTo(0, 300)')
                await page.wait_for_timeout(1000)
                await page.evaluate('window.scrollTo(0, 0)')
                await page.wait_for_timeout(1000)
                
                # 鼠标移动和点击
                await page.mouse.move(200, 200)
                await page.wait_for_timeout(500)
                await page.mouse.move(400, 300)
                await page.wait_for_timeout(500)
                
                logging.info("用户行为模拟完成")
            except Exception as e:
                logging.warning(f"模拟用户行为时出错: {e}")
            
            # 再等待一段时间让反机器人系统完全初始化
            logging.info("等待反机器人系统完全初始化...")
            await page.wait_for_timeout(5000)
            
            # 检查是否有PX相关的cookies
            cookies = await page.context.cookies()
            px_cookies = [c for c in cookies if 'px' in c['name'].lower()]
            all_cookies = [c for c in cookies if c['domain'] in ['.ifood.com.br', 'ifood.com.br', '.cw-marketplace.ifood.com.br']]
            
            if px_cookies:
                logging.info(f"检测到PX反机器人cookies: {[c['name'] for c in px_cookies]}")
                for cookie in px_cookies:
                    logging.info(f"  PX Cookie: {cookie['name']} = {cookie['value'][:50]}...")
            else:
                logging.warning("未检测到PX反机器人cookies，可能会导致403错误")
            
            if all_cookies:
                logging.info(f"检测到所有相关cookies: {[c['name'] for c in all_cookies]}")
            else:
                logging.warning("未检测到任何相关cookies")
                
            # 尝试手动触发一些页面交互来激活PX系统
            try:
                logging.info("尝试触发页面交互以激活PX系统...")
                await page.mouse.move(100, 100)
                await page.wait_for_timeout(1000)
                await page.mouse.move(200, 200)
                await page.wait_for_timeout(2000)
                
                # 再次检查cookies
                cookies_after = await page.context.cookies()
                px_cookies_after = [c for c in cookies_after if 'px' in c['name'].lower()]
                if len(px_cookies_after) > len(px_cookies):
                    logging.info(f"页面交互后新增PX cookies: {[c['name'] for c in px_cookies_after if c not in px_cookies]}")
            except Exception as e:
                logging.warning(f"页面交互时出错: {e}")
            
            # 现在设置API拦截并重新加载页面以触发API调用
            logging.info(f"开始设置API拦截模式，等待以下API响应:")
            for key, pattern in api_patterns.items():
                logging.info(f"  - {key}: {pattern.pattern}")
            
            response_awaitables = [
                page.wait_for_event(
                    "response",
                    lambda res, p=pattern: p.search(res.url),
                    timeout=request_timeout  # 使用环境变量配置的超时时间
                )
                for pattern in api_patterns.values()
            ]
            
            # 不重新加载页面，而是通过JavaScript触发API调用
            logging.info("通过页面交互触发API调用...")
            try:
                # 尝试点击页面上的元素来触发API调用
                await page.evaluate('''
                    // 尝试触发页面上的事件来激活API调用
                    window.dispatchEvent(new Event('focus'));
                    window.dispatchEvent(new Event('load'));
                    
                    // 如果页面有特定的触发器，尝试调用
                    if (window.location.reload) {
                        setTimeout(() => {
                            window.location.reload();
                        }, 100);
                    }
                ''')
                
                # 等待API调用被触发
                navigation_awaitable = page.wait_for_load_state('networkidle', timeout=request_timeout)
                
            except Exception as e:
                logging.warning(f"JavaScript触发失败，回退到页面重新加载: {e}")
                navigation_awaitable = page.reload(wait_until='networkidle', timeout=request_timeout)
            
            all_results = await asyncio.gather(
                *response_awaitables, navigation_awaitable, return_exceptions=True
            )
            
            # 计算响应时间
            response_time = time.time() - start_time
            
            # 【修复】增加明确的日志记录，以解释为何失败
            # 1. 检查导航任务本身是否失败
            navigation_result = all_results[-1]
            if isinstance(navigation_result, Exception):
                logging.error(f"页面导航失败: {type(navigation_result).__name__} - {navigation_result}")
            else:
                # 检查页面是否成功打开
                if hasattr(navigation_result, 'ok') and navigation_result.ok:
                    logging.info(f"✅ 页面成功打开: {target_url} [状态: {navigation_result.status}]")
                elif hasattr(navigation_result, 'status'):
                    logging.warning(f"⚠️ 页面打开但返回异常状态: {target_url} [状态: {navigation_result.status}]")
                else:
                    logging.info(f"✅ 页面导航完成: {target_url}")

            # 2. 检查各个API响应的等待任务是否失败
            response_results = all_results[:-1]
            api_keys = list(api_patterns.keys())
            for i, res in enumerate(response_results):
                if isinstance(res, Exception):
                    logging.error(f"等待 API '{api_keys[i]}' 响应时失败: {type(res).__name__}")
            
            scraped_responses = dict(zip(api_keys, response_results))
            
            logging.info(f"API拦截结果统计:")
            for key, response in scraped_responses.items():
                if isinstance(response, Exception):
                    logging.info(f"  - {key}: 异常 - {type(response).__name__}")
                else:
                    logging.info(f"  - {key}: 成功 - URL: {response.url}, 状态: {response.status}")

            # 在浏览器关闭前处理所有响应
            processing_tasks = [
                _process_api_response(key, response)
                for key, response in scraped_responses.items()
            ]
            processed_results_list = await asyncio.gather(*processing_tasks)
            
            # 检查请求是否成功
            has_success = any("error" not in result for result in processed_results_list if isinstance(result, dict))
            
            # 记录最终处理结果
            final_results = dict(zip(api_keys, processed_results_list))
            logging.info(f"最终处理结果:")
            for key, result in final_results.items():
                if isinstance(result, dict) and "error" in result:
                    logging.info(f"  - {key}: 错误 - {result.get('error', 'Unknown')}: {result.get('message', 'No message')}")
                else:
                    if key == "menu" and isinstance(result, dict):
                        categories_count = len(result.get("categories", []))
                        logging.info(f"  - {key}: 成功 - 包含 {categories_count} 个分类")
                    else:
                        logging.info(f"  - {key}: 成功 - 数据类型: {type(result)}")
            
            # 记录代理使用结果
            if has_success:
                record_proxy_result(proxy_config, True, response_time)
            else:
                record_proxy_result(proxy_config, False, response_time, "all_apis_failed")
            
            return final_results

        except Exception as e:
            error_message = str(e)
            error_type = type(e).__name__
            
            # 更详细的错误分类和处理
            if isinstance(e, TimeoutError):
                error_message = "操作超时。可能原因：页面加载过慢、未触发API请求、或被CAPTCHA阻挡。"
                error_type = "TimeoutError"
            elif "net::ERR_" in error_message:
                error_message = "网络连接错误。可能是代理问题或网站不可达。"
                error_type = "NetworkError"
            elif "browserless" in error_message.lower():
                error_message = "浏览器服务错误。建议检查浏览器配置或内存限制。"
                error_type = "BrowserError"
            elif "memory" in error_message.lower() or "out of memory" in error_message.lower():
                error_message = "内存不足错误。建议优化浏览器参数或增加Cloud Function内存。"
                error_type = "MemoryError"
                
            logging.error(f"抓取过程中发生错误 [{error_type}]: {error_message}")
            
            # 记录代理失败
            if 'start_time' in locals():
                response_time = time.time() - start_time
            else:
                response_time = 0.0
            record_proxy_result(proxy_config, False, response_time, error_type)
            
            # 记录更多调试信息用于 Cloud Function 环境
            if IS_CLOUD_FUNCTION:
                import psutil
                try:
                    memory_usage = psutil.virtual_memory()
                    logging.info(f"当前内存使用: {memory_usage.percent}% ({memory_usage.used / 1024 / 1024:.1f}MB / {memory_usage.total / 1024 / 1024:.1f}MB)")
                except ImportError:
                    logging.info("psutil 不可用，无法获取内存使用信息")
            
            return {
                key: {
                    "error": error_type, 
                    "message": error_message, 
                    "status": 500,
                    "is_cloud_function": IS_CLOUD_FUNCTION
                }
                for key in api_patterns.keys()
            }
        finally:
            # 更好的资源清理，参考 Browserless 建议
            if browser:
                try:
                    if browser.is_connected():
                        # 先关闭所有页面
                        contexts = browser.contexts
                        for context in contexts:
                            await context.close()
                        
                        # 然后关闭浏览器
                        await browser.close()
                        logging.info("浏览器和所有上下文已安全关闭。")
                    else:
                        logging.info("浏览器已断开连接。")
                except Exception as cleanup_error:
                    logging.warning(f"清理浏览器资源时出错: {cleanup_error}")
                    
            # 在 Cloud Function 环境中强制垃圾回收
            if IS_CLOUD_FUNCTION:
                import gc
                gc.collect()
                logging.info("已执行垃圾回收。")

async def _scrape_ifood_page_dom_fallback(
    target_url: str,
    proxy_config: Optional[Dict[str, str]]
) -> Dict[str, Any]:
    """
    DOM解析备用方案：直接解析页面内容而不依赖API拦截
    """
    async with async_playwright() as p:
        browser = None
        try:
            # 根据环境变量获取超时配置
            browser_timeout = int(os.getenv("BROWSER_TIMEOUT", "90")) * 1000  # 默认90秒
            request_timeout = int(os.getenv("REQUEST_TIMEOUT", "120")) * 1000  # 默认120秒
            
            # 启动浏览器
            launch_options = {
                "headless": True,
                "timeout": browser_timeout,
                "args": _get_optimized_browser_args()
            }
            
            if proxy_config:
                launch_options["proxy"] = proxy_config
                logging.info("DOM备用方案：通过代理启动浏览器...")
            else:
                logging.info("DOM备用方案：直接启动浏览器...")
            
            browser = await _launch_browser_with_fallback(p, launch_options)
            
            # 获取随机隐身配置
            stealth_config = get_random_stealth_config()
            
            page = await browser.new_page(
                user_agent=stealth_config.user_agent,
                viewport={"width": stealth_config.viewport_width, "height": stealth_config.viewport_height},
                extra_http_headers=get_realistic_headers()
            )
            
            # 设置地理位置权限和坐标（DOM备用方案）
            context = page.context
            await context.grant_permissions(['geolocation'])
            logging.info("DOM备用方案：设置地理位置为圣保罗...")
            await context.set_geolocation({"latitude": -23.5505, "longitude": -46.6333})  # 圣保罗坐标
            
            # 注入反检测脚本
            for script in get_stealth_page_scripts():
                await page.add_init_script(script)
            
            # 注入地理位置模拟脚本（DOM备用方案）
            geolocation_script = """
                // 覆盖地理位置API，强制返回圣保罗坐标
                Object.defineProperty(navigator.geolocation, 'getCurrentPosition', {
                    value: function(success, error, options) {
                        const position = {
                            coords: {
                                latitude: -23.5505,
                                longitude: -46.6333,
                                accuracy: 10,
                                altitude: null,
                                altitudeAccuracy: null,
                                heading: null,
                                speed: null
                            },
                            timestamp: Date.now()
                        };
                        if (success) {
                            success(position);
                        }
                    }
                });
                
                Object.defineProperty(navigator.geolocation, 'watchPosition', {
                    value: function(success, error, options) {
                        const position = {
                            coords: {
                                latitude: -23.5505,
                                longitude: -46.6333,
                                accuracy: 10,
                                altitude: null,
                                altitudeAccuracy: null,
                                heading: null,
                                speed: null
                            },
                            timestamp: Date.now()
                        };
                        if (success) {
                            success(position);
                        }
                        return 1; // 返回watchId
                    }
                });
            """
            await page.add_init_script(geolocation_script)
            
            # 设置超时
            page.set_default_navigation_timeout(request_timeout)
            page.set_default_timeout(request_timeout)
            
            # 拦截并修改API请求，强制添加地理位置参数（DOM备用方案）
            async def handle_api_request_dom(route):
                request = route.request
                url = request.url
                
                # 检查是否是需要阻断的资源（图片、CSS等）
                if IS_CLOUD_FUNCTION and any(ext in url.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.css']):
                    await route.abort()
                    return
                
                # 如果是iFood的API请求，记录详细信息并修改（DOM备用方案）
                if "cw-marketplace.ifood.com.br" in url or "merchant-info/graphql" in url:
                    # 记录原始请求详情
                    logging.info(f"📡 DOM备用方案：拦截到iFood API请求:")
                    logging.info(f"  URL: {url}")
                    logging.info(f"  方法: {request.method}")
                    logging.info(f"  请求头: {dict(request.headers)}")
                    if request.post_data:
                        logging.info(f"  POST数据: {request.post_data}")
                    
                    # 如果缺少地理位置参数，则修改URL
                    if "latitude=&" in url or "longitude=&" in url:
                        modified_url = url.replace("latitude=&longitude=", "latitude=-23.5505&longitude=-46.6333")
                        logging.info(f"🔧 DOM备用方案：修改API请求URL: {url} -> {modified_url}")
                        await route.continue_(url=modified_url)
                    else:
                        await route.continue_()
                else:
                    # 正常继续请求
                    await route.continue_()
            
            # 应用统一的请求拦截器（DOM备用方案）
            await page.route("**/*", handle_api_request_dom)
            
            logging.info(f"DOM备用方案：导航到 {target_url}")
            
            # 导航到页面 - 只等待导航开始，不等待DOM加载
            try:
                navigation_response = await page.goto(target_url, wait_until='commit', timeout=request_timeout)
                
                # 检查页面是否成功打开
                if navigation_response and navigation_response.ok:
                    logging.info(f"✅ DOM备用方案：页面成功打开: {target_url} [状态: {navigation_response.status}]")
                elif navigation_response:
                    logging.warning(f"⚠️ DOM备用方案：页面打开但返回异常状态: {target_url} [状态: {navigation_response.status}]")
                else:
                    logging.warning(f"⚠️ DOM备用方案：页面导航完成但无响应信息: {target_url}")
            except Exception as nav_error:
                logging.error(f"❌ DOM备用方案：页面导航失败: {target_url} - {type(nav_error).__name__}: {nav_error}")
                raise nav_error
            
            # 不等待页面加载完成，直接进行API拦截
            
            # 等待页面基本加载完成
            await page.wait_for_timeout(3000)
            
            # 检查页面内容，看是否需要地址输入
            try:
                page_content = await page.content()
                
                # 检查页面是否包含地址相关的文本
                address_indicators = [
                    "Escolha um endereço", "Informe seu endereço", 
                    "Você verá apenas os restaurantes", "entregam onde você está"
                ]
                
                needs_address = any(indicator in page_content for indicator in address_indicators)
                
                if needs_address:
                    logging.info("DOM备用方案：检测到需要地址的页面内容，尝试处理地址输入...")
                    
                    # 尝试查找并点击地址相关的按钮或输入框
                    address_triggers = [
                        'button:has-text("Informe seu endereço")',
                        'button:has-text("Escolha um endereço")',
                        'button:has-text("Ignorar")',
                        'button:has-text("Informar")',
                        'div:has-text("Informe seu endereço")',
                        'div:has-text("Escolha um endereço")',
                        'input[placeholder*="endereço"]',
                        'input[placeholder*="CEP"]',
                        'input[placeholder*="address"]',
                        'input[type="text"]',
                        '[data-testid="address-input"]',
                        '.address-input',
                        '[data-testid="location-input"]',
                        '.location-input'
                    ]
                    
                    address_triggered = False
                    address_attempts = 0
                    
                    # 首先尝试点击"Ignorar"按钮（如果存在）
                    try:
                        ignore_button = await page.query_selector('button:has-text("Ignorar")')
                        if ignore_button:
                            await ignore_button.click()
                            await page.wait_for_timeout(2000)
                            logging.info("DOM备用方案：已点击'Ignorar'按钮，尝试跳过地址输入")
                            
                            # 检查是否成功跳过
                            new_content = await page.content()
                            if not any(indicator in new_content for indicator in address_indicators):
                                address_triggered = True
                                logging.info("DOM备用方案：成功跳过地址输入")
                    except Exception as e:
                        logging.info(f"尝试点击'Ignorar'按钮时出错: {str(e)}")
                    
                    # 如果跳过失败，尝试输入地址
                    if not address_triggered:
                        for selector in address_triggers:
                            if address_attempts >= 3:  # 限制尝试次数
                                break
                                
                            try:
                                elements = await page.query_selector_all(selector)
                                for element in elements:
                                    try:
                                        # 如果是输入框，直接输入
                                        tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                                        if tag_name == 'input':
                                            # 尝试多个地址格式
                                            test_addresses = [
                                                "Rua Augusta, 123, São Paulo, SP",
                                                "Av. Paulista, 1000, São Paulo, SP",
                                                "Rua Oscar Freire, 456, São Paulo, SP"
                                            ]
                                            
                                            for address in test_addresses:
                                                try:
                                                    await element.fill(address)
                                                    await page.wait_for_timeout(1000)
                                                    await element.press('Enter')
                                                    await page.wait_for_timeout(3000)
                                                    
                                                    # 检查是否成功
                                                    current_content = await page.content()
                                                    if not any(indicator in current_content for indicator in address_indicators):
                                                        logging.info(f"DOM备用方案：成功输入地址: {address}")
                                                        address_triggered = True
                                                        break
                                                except Exception:
                                                    continue
                                            
                                            if address_triggered:
                                                break
                                        else:
                                            # 如果是按钮或div，点击它
                                            await element.click()
                                            await page.wait_for_timeout(2000)
                                            logging.info("DOM备用方案：已点击地址相关元素")
                                            
                                            # 点击后可能出现输入框，再次尝试输入
                                            new_inputs = await page.query_selector_all('input[type="text"], input[placeholder*="endereço"], input[placeholder*="CEP"]')
                                            for input_elem in new_inputs:
                                                try:
                                                    await input_elem.fill("Rua Augusta, 123, São Paulo, SP")
                                                    await page.wait_for_timeout(1000)
                                                    await input_elem.press('Enter')
                                                    await page.wait_for_timeout(3000)
                                                    logging.info("DOM备用方案：已在弹出的输入框中输入地址")
                                                    address_triggered = True
                                                    break
                                                except Exception:
                                                    continue
                                            
                                            if address_triggered:
                                                break
                                    except Exception as e:
                                        logging.warning(f"处理地址元素时出错: {str(e)}")
                                        continue
                                
                                if address_triggered:
                                    break
                                    
                            except Exception as e:
                                logging.warning(f"查找地址元素时出错 [{selector}]: {str(e)}")
                                continue
                            
                            address_attempts += 1
                    
                    if address_triggered:
                        # 等待页面更新 - 增加等待时间
                        logging.info("DOM备用方案：等待页面搜索完成...")
                        await page.wait_for_timeout(8000)  # 增加到8秒
                        
                        # 等待搜索完成 - 检查页面是否还在搜索状态
                        search_complete = False
                        for attempt in range(15):  # 最多等待30秒
                            try:
                                page_text = await page.text_content('body')
                                if page_text and 'Buscando por' not in page_text:
                                    # 检查是否出现了菜单内容
                                    if 'menu' in page_text.lower() or 'cardápio' in page_text.lower() or 'categoria' in page_text.lower():
                                        search_complete = True
                                        logging.info(f"DOM备用方案：搜索完成，检测到菜单内容 (尝试 {attempt + 1})")
                                        break
                                    else:
                                        logging.info(f"DOM备用方案：搜索完成，但未检测到菜单内容 (尝试 {attempt + 1})")
                                        # 继续等待，可能菜单还在加载
                                        await page.wait_for_timeout(2000)
                                else:
                                    logging.info(f"DOM备用方案：仍在搜索中... (尝试 {attempt + 1})")
                                    await page.wait_for_timeout(2000)
                            except Exception:
                                await page.wait_for_timeout(2000)
                        
                        if not search_complete:
                            logging.warning("DOM备用方案：搜索可能未完成，继续处理...")
                        
                        # 给页面更多时间加载菜单内容
                        await page.wait_for_timeout(5000)  # 增加到5秒
                        logging.info("DOM备用方案：地址输入完成，继续处理")
                        
                        # 调试：保存页面截图（仅在云环境中）
                        if IS_CLOUD_FUNCTION or IS_CLOUD_RUN:
                            try:
                                await page.screenshot(path='/tmp/page_after_address.png')
                                logging.info("DOM备用方案：已保存地址输入后的页面截图")
                            except Exception:
                                pass
                    else:
                        logging.warning("DOM备用方案：未能成功触发地址输入")
                        
                        # 调试：保存当前页面截图和HTML
                        if IS_CLOUD_FUNCTION or IS_CLOUD_RUN:
                            try:
                                await page.screenshot(path='/tmp/page_no_address.png')
                                with open('/tmp/page_content.html', 'w', encoding='utf-8') as f:
                                    f.write(page_content[:5000])  # 只保存前5000字符
                                logging.info("DOM备用方案：已保存无法输入地址时的页面截图和内容")
                            except Exception:
                                pass
                else:
                    logging.info("DOM备用方案：页面不需要地址输入")
                    
            except Exception as e:
                logging.warning(f"地址处理时出错: {str(e)}")
            
            # 等待关键元素出现
            try:
                # 等待店铺名称或菜单容器出现
                await page.wait_for_selector('[data-testid="merchant-header"], .merchant-header, h1', timeout=30000)
            except TimeoutError:
                logging.warning("DOM备用方案：未找到关键元素，继续尝试解析...")
            
            # 提取店铺信息
            shop_info = await _extract_shop_info_from_dom(page)
            logging.info(f"DOM解析店铺信息结果: {shop_info}")
            
            # 提取菜单信息
            menu_info = await _extract_menu_info_from_dom(page)
            logging.info(f"DOM解析菜单信息结果: {menu_info}")
            
            return {
                "shop_info": shop_info,
                "menu": menu_info
            }
            
        except Exception as e:
            logging.error(f"DOM备用方案失败: {type(e).__name__} - {str(e)}")
            return {
                "shop_info": {"error": "DOMFallbackError", "message": f"DOM解析失败: {str(e)}"},
                "menu": {"error": "DOMFallbackError", "message": f"DOM解析失败: {str(e)}"}
            }
        finally:
            if browser:
                try:
                    if browser.is_connected():
                        contexts = browser.contexts
                        for context in contexts:
                            await context.close()
                        await browser.close()
                        logging.info("DOM备用方案：浏览器已关闭")
                except Exception as cleanup_error:
                    logging.warning(f"DOM备用方案：清理浏览器时出错: {cleanup_error}")

async def _extract_shop_info_from_dom(page) -> Dict[str, Any]:
    """从DOM中提取店铺信息"""
    try:
        shop_info = {}
        
        # 等待页面加载完成
        await page.wait_for_timeout(3000)  # 等待3秒让页面完全加载
        
        # 提取店铺名称 - 使用更广泛的选择器
        name_selectors = [
            'h1',
            '[data-testid="merchant-header"] h1',
            '.merchant-header h1',
            '[data-testid="merchant-name"]',
            '.merchant-name',
            '.restaurant-name',
            '.store-name',
            'header h1',
            '.merchant-info h1',
            '.merchant-title',
            'div[class*="merchant"] h1',
            'div[class*="restaurant"] h1'
        ]
        
        for selector in name_selectors:
            try:
                name_element = await page.query_selector(selector)
                if name_element:
                    name_text = await name_element.text_content()
                    if name_text and name_text.strip():
                        shop_info['name'] = name_text.strip()
                        logging.info(f"找到店铺名称: {shop_info['name']} (使用选择器: {selector})")
                        break
            except Exception:
                continue
        
        # 如果还是没找到名称，尝试从页面标题获取
        if not shop_info.get('name'):
            try:
                title = await page.title()
                if title and 'ifood' in title.lower():
                    # 从标题中提取店铺名称
                    import re
                    title_match = re.search(r'^([^-|]+)', title)
                    if title_match:
                        shop_info['name'] = title_match.group(1).strip()
                        logging.info(f"从页面标题提取店铺名称: {shop_info['name']}")
            except Exception:
                pass
        
        # 提取评分 - 使用更广泛的选择器
        rating_selectors = [
            '[data-testid="rating"]',
            '.rating',
            '.star-rating',
            '.merchant-rating',
            '.restaurant-rating',
            'div[class*="rating"]',
            'span[class*="rating"]',
            'div[class*="star"]'
        ]
        
        for selector in rating_selectors:
            try:
                rating_element = await page.query_selector(selector)
                if rating_element:
                    rating_text = await rating_element.text_content()
                    if rating_text:
                        import re
                        rating_match = re.search(r'(\d+[.,]\d+|\d+)', rating_text)
                        if rating_match:
                            rating_str = rating_match.group(1).replace(',', '.')
                            shop_info['rating'] = float(rating_str)
                            logging.info(f"找到评分: {shop_info['rating']} (使用选择器: {selector})")
                            break
            except Exception:
                continue
        
        # 提取配送时间
        delivery_selectors = [
            '[data-testid="delivery-time"]',
            '.delivery-time',
            '.delivery-info',
            'div[class*="delivery"]',
            'span[class*="delivery"]',
            'div[class*="time"]'
        ]
        
        for selector in delivery_selectors:
            try:
                delivery_element = await page.query_selector(selector)
                if delivery_element:
                    delivery_text = await delivery_element.text_content()
                    if delivery_text and delivery_text.strip():
                        shop_info['delivery_time'] = delivery_text.strip()
                        logging.info(f"找到配送时间: {shop_info['delivery_time']} (使用选择器: {selector})")
                        break
            except Exception:
                continue
        
        # 提取配送费
        fee_selectors = [
            '[data-testid="delivery-fee"]',
            '.delivery-fee',
            '.delivery-cost',
            'div[class*="fee"]',
            'span[class*="fee"]',
            'div[class*="cost"]'
        ]
        
        for selector in fee_selectors:
            try:
                fee_element = await page.query_selector(selector)
                if fee_element:
                    fee_text = await fee_element.text_content()
                    if fee_text and fee_text.strip():
                        shop_info['delivery_fee'] = fee_text.strip()
                        logging.info(f"找到配送费: {shop_info['delivery_fee']} (使用选择器: {selector})")
                        break
            except Exception:
                continue
        
        # 提取地址
        address_selectors = [
            '[data-testid="address"]',
            '.address',
            '.merchant-address',
            '.restaurant-address',
            'div[class*="address"]',
            'span[class*="address"]'
        ]
        
        for selector in address_selectors:
            try:
                address_element = await page.query_selector(selector)
                if address_element:
                    address_text = await address_element.text_content()
                    if address_text and address_text.strip():
                        shop_info['address'] = address_text.strip()
                        logging.info(f"找到地址: {shop_info['address']} (使用选择器: {selector})")
                        break
            except Exception:
                continue
        
        # 记录找到的所有信息
        logging.info(f"DOM解析提取到的店铺信息: {shop_info}")
        
        if shop_info:
            return shop_info
        else:
            return {"error": "NoShopInfo", "message": "未能从DOM中提取到店铺信息"}
            
    except Exception as e:
        logging.error(f"提取店铺信息失败: {str(e)}")
        return {"error": "ShopInfoExtractionError", "message": f"提取店铺信息时出错: {str(e)}"}

async def _extract_menu_info_from_dom(page) -> Dict[str, Any]:
    """从DOM中提取菜单信息"""
    try:
        menu_info = {"categories": []}
        
        # 等待菜单加载
        await page.wait_for_timeout(2000)  # 等待2秒让菜单加载
        
        # 调试：记录页面基本信息
        try:
            page_title = await page.title()
            logging.info(f"菜单提取：页面标题: {page_title}")
            
            # 检查页面是否包含地址相关提示
            page_text = await page.text_content('body')
            if page_text:
                if "Escolha um endereço" in page_text or "Informe seu endereço" in page_text:
                    logging.warning("菜单提取：页面仍显示地址输入提示，可能地址输入未成功")
                if "Buscando por" in page_text:
                    logging.info("菜单提取：页面正在搜索中...")
                if "menu" in page_text.lower() or "cardápio" in page_text.lower():
                    logging.info("菜单提取：页面包含菜单相关内容")
        except Exception as e:
            logging.warning(f"菜单提取：获取页面基本信息时出错: {str(e)}")
        
        # 查找菜单分类 - 使用更广泛的选择器
        category_selectors = [
            '[data-testid="category"]',
            '.category',
            '.menu-category',
            '.product-category',
            'section[class*="category"]',
            'div[class*="category"]',
            'section[class*="menu"]',
            'div[class*="menu-section"]',
            'div[class*="product-section"]',
            '.menu-group',
            '.product-group',
            '[data-testid="menu-section"]',
            '[data-testid="product-section"]',
            '.restaurant-menu',
            '.store-menu',
            '.merchant-menu'
        ]
        
        category_elements = []
        for selector in category_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    category_elements = elements
                    logging.info(f"找到 {len(elements)} 个分类元素 (使用选择器: {selector})")
                    break
            except Exception:
                continue
        
        # 如果没找到分类，尝试查找所有商品
        if not category_elements:
            logging.info("未找到分类，尝试直接查找商品...")
            item_selectors = [
                '[data-testid="menu-item"]',
                '[data-testid="product-item"]',
                '[data-testid="dish-item"]',
                '.menu-item',
                '.product-item',
                '.dish-item',
                '.food-item',
                'div[class*="product"]',
                'div[class*="item"]',
                'div[class*="dish"]',
                'article[class*="product"]',
                'article[class*="item"]',
                'article[class*="dish"]',
                'li[class*="product"]',
                'li[class*="item"]',
                'li[class*="dish"]'
            ]
            
            all_items = []
            for selector in item_selectors:
                try:
                    items = await page.query_selector_all(selector)
                    if items:
                        all_items = items
                        logging.info(f"找到 {len(items)} 个商品 (使用选择器: {selector})")
                        break
                except Exception:
                    continue
            
            if all_items:
                # 创建一个通用分类
                category_info = {
                    'name': '菜单',
                    'items': []
                }
                
                for item_element in all_items:
                    item_info = await _extract_item_info(item_element)
                    if item_info.get('name'):
                        category_info['items'].append(item_info)
                
                if category_info['items']:
                    menu_info['categories'].append(category_info)
        else:
            # 处理找到的分类
            for i, category_element in enumerate(category_elements):
                try:
                    category_info = {}
                    
                    # 调试：记录分类元素的基本信息
                    try:
                        element_html = await category_element.inner_html()
                        logging.info(f"处理分类元素 {i+1}: HTML长度={len(element_html)}")
                    except Exception:
                        pass
                    
                    # 提取分类名称 - 使用更广泛的选择器
                    name_selectors = [
                        'h2', 'h3', 'h4',
                        '.category-name',
                        '.category-title',
                        '.section-title',
                        '.menu-title',
                        'div[class*="title"]',
                        'span[class*="title"]',
                        'div[class*="name"]',
                        'span[class*="name"]'
                    ]
                    
                    for selector in name_selectors:
                        try:
                            name_element = await category_element.query_selector(selector)
                            if name_element:
                                name_text = await name_element.text_content()
                                if name_text and name_text.strip():
                                    category_info['name'] = name_text.strip()
                                    break
                        except Exception:
                            continue
                    
                    # 如果没找到分类名称，使用默认名称
                    if not category_info.get('name'):
                        category_info['name'] = f'分类 {len(menu_info["categories"]) + 1}'
                    
                    # 提取该分类下的商品
                    item_selectors = [
                        '[data-testid="menu-item"]',
                        '[data-testid="product-item"]',
                        '[data-testid="dish-item"]',
                        '.menu-item',
                        '.product-item',
                        '.dish-item',
                        '.food-item',
                        'div[class*="product"]',
                        'div[class*="item"]',
                        'div[class*="dish"]',
                        'article[class*="product"]',
                        'article[class*="item"]',
                        'article[class*="dish"]',
                        'li[class*="product"]',
                        'li[class*="item"]',
                        'li[class*="dish"]'
                    ]
                    
                    category_info['items'] = []
                    for selector in item_selectors:
                        try:
                            item_elements = await category_element.query_selector_all(selector)
                            if item_elements:
                                for item_element in item_elements:
                                    item_info = await _extract_item_info(item_element)
                                    if item_info.get('name'):
                                        category_info['items'].append(item_info)
                                break
                        except Exception:
                            continue
                    
                    # 即使没有商品，也保存分类信息（用于调试）
                    if category_info.get('name'):
                        if not category_info.get('items'):
                            category_info['items'] = []
                        menu_info['categories'].append(category_info)
                        logging.info(f"提取分类: {category_info['name']} ({len(category_info['items'])} 个商品)")
                    else:
                        logging.warning(f"分类元素未找到名称，跳过")
                        
                except Exception as e:
                    logging.warning(f"提取菜单分类时出错: {str(e)}")
                    continue
        
        # 记录结果
        logging.info(f"DOM解析提取到的菜单信息: {len(menu_info['categories'])} 个分类")
        
        # 详细记录每个分类的内容
        for i, category in enumerate(menu_info['categories']):
            category_name = category.get('name', '未知分类')
            items_count = len(category.get('items', []))
            logging.info(f"  分类 {i+1}: {category_name} - 商品数量: {items_count}")
            
            # 记录前几个商品的信息
            items = category.get('items', [])
            for j, item in enumerate(items[:3]):  # 只记录前3个商品
                if isinstance(item, dict):
                    item_name = item.get('name', '未知商品')
                    item_price = item.get('price', '无价格')
                    logging.info(f"    商品 {j+1}: {item_name} - 价格: {item_price}")
            
            if len(items) > 3:
                logging.info(f"    ... 还有 {len(items) - 3} 个商品")
        
        if menu_info['categories']:
            return menu_info
        else:
            return {"error": "NoMenuInfo", "message": "未能从DOM中提取到菜单信息"}
            
    except Exception as e:
        logging.error(f"提取菜单信息失败: {str(e)}")
        return {"error": "MenuExtractionError", "message": f"提取菜单信息时出错: {str(e)}"}

async def _extract_item_info(item_element) -> Dict[str, Any]:
    """从单个商品元素中提取信息"""
    try:
        item_info = {}
        
        # 商品名称 - 使用更广泛的选择器
        name_selectors = [
            '.item-name',
            '.product-name',
            '.dish-name',
            'h4', 'h5', 'h6',
            'div[class*="name"]',
            'span[class*="name"]',
            'div[class*="title"]',
            'span[class*="title"]',
            '.name',
            '.title'
        ]
        
        for selector in name_selectors:
            try:
                name_element = await item_element.query_selector(selector)
                if name_element:
                    name_text = await name_element.text_content()
                    if name_text and name_text.strip():
                        item_info['name'] = name_text.strip()
                        break
            except Exception:
                continue
        
        # 商品价格 - 使用更广泛的选择器
        price_selectors = [
            '.price',
            '.item-price',
            '.product-price',
            '.cost',
            'div[class*="price"]',
            'span[class*="price"]',
            'div[class*="cost"]',
            'span[class*="cost"]'
        ]
        
        for selector in price_selectors:
            try:
                price_element = await item_element.query_selector(selector)
                if price_element:
                    price_text = await price_element.text_content()
                    if price_text:
                        # 清理价格文本
                        import re
                        price_match = re.search(r'R\$\s*(\d+[,.]?\d*)', price_text)
                        if price_match:
                            item_info['price'] = price_match.group(0)
                            break
            except Exception:
                continue
        
        # 商品描述 - 使用更广泛的选择器
        desc_selectors = [
            '.description',
            '.item-description',
            '.product-description',
            '.dish-description',
            'div[class*="description"]',
            'span[class*="description"]',
            'p[class*="description"]',
            '.desc',
            'p'
        ]
        
        for selector in desc_selectors:
            try:
                desc_element = await item_element.query_selector(selector)
                if desc_element:
                    desc_text = await desc_element.text_content()
                    if desc_text and desc_text.strip() and desc_text.strip() != item_info.get('name', ''):
                        item_info['description'] = desc_text.strip()
                        break
            except Exception:
                continue
        
        return item_info
        
    except Exception as e:
        logging.warning(f"提取商品信息时出错: {str(e)}")
        return {}

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
    直接使用API拦截策略获取店铺信息和菜单数据，跳过DOM解析。
    """
    logging.info("使用API拦截策略获取店铺和菜单信息...")
    
    # 同时拦截店铺信息和菜单API
    api_patterns = {
        "shop_info": re.compile(r"merchant-info/graphql"),
        "menu": re.compile(r"merchants/.*/catalog")
    }
    
    try:
        # 使用API拦截获取数据
        api_result = await _scrape_ifood_page(target_url, proxy_config, api_patterns)
        
        # 检查API拦截结果
        shop_info = api_result.get("shop_info", {})
        menu = api_result.get("menu", {})
        
        # 记录结果状态
        if isinstance(shop_info, dict) and "error" not in shop_info:
            logging.info("API拦截成功获取店铺信息")
        else:
            logging.warning("API拦截未能获取店铺信息")
            
        if isinstance(menu, dict) and "error" not in menu:
            logging.info("API拦截成功获取菜单信息")
        else:
            logging.warning("API拦截未能获取菜单信息")
        
        return {
            "shop_info": shop_info,
            "menu": menu
        }
        
    except Exception as e:
        logging.error(f"API拦截过程中发生错误: {str(e)}")
        return {
            "shop_info": {"error": "APIInterceptionError", "message": f"API拦截失败: {str(e)}"},
            "menu": {"error": "APIInterceptionError", "message": f"API拦截失败: {str(e)}"}
        }

# --- API 端点 ---

@app.get("/health", summary="健康检查", status_code=200)
async def health_check():
    """
    健康检查端点，返回服务状态信息。
    """
    import psutil
    import platform
    
    try:
        # 获取系统信息
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        health_info = {
            "status": "healthy",
            "timestamp": asyncio.get_event_loop().time(),
            "version": "1.0.0",
            "environment": {
                "is_cloud_function": IS_CLOUD_FUNCTION,
                "gcp_region": GCP_REGION if IS_CLOUD_FUNCTION else None,
                "proxy_strategy": PROXY_ROTATION_STRATEGY,
                "platform": platform.platform(),
                "python_version": platform.python_version()
            },
            "system": {
                "memory_usage_percent": memory.percent,
                "memory_available_mb": memory.available / 1024 / 1024,
                "cpu_percent": cpu_percent,
                "disk_usage_percent": psutil.disk_usage('/').percent
            },
                    "proxy": {
            "disabled": DISABLE_PROXY,
            "cloud_proxy_configured": bool(CLOUD_PROXY_HOST) if not DISABLE_PROXY else False,
            "local_proxy_file_exists": os.path.exists(PROXY_FILE) if not DISABLE_PROXY else False
        }
        }
        
        return health_info
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": asyncio.get_event_loop().time()
        }

@app.get("/status", summary="详细状态信息", status_code=200)
async def status_info(token: str = Depends(verify_token)):
    """
    获取详细的系统状态信息，需要认证。
    """
    import psutil
    import platform
    from datetime import datetime
    
    # 获取代理配置信息
    proxy_config = get_random_proxy_config()
    proxy_info = "无代理" if proxy_config is None else f"代理: {proxy_config.get('server', '未知')}"
    
    # 获取智能代理管理器统计信息
    proxy_stats = proxy_manager.get_proxy_stats_summary()
    
    status_info = {
        "service": "iFood Menu API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "uptime": asyncio.get_event_loop().time(),
        "proxy_config": proxy_info,
        "proxy_manager_stats": proxy_stats if not DISABLE_PROXY else {"disabled": True, "message": "代理功能已禁用"},
        "environment": {
            "is_cloud_function": IS_CLOUD_FUNCTION,
            "gcp_region": GCP_REGION if IS_CLOUD_FUNCTION else None,
            "use_gcp_ip_rotation": USE_GCP_NATURAL_IP_ROTATION,
            "proxy_rotation_strategy": PROXY_ROTATION_STRATEGY
        },
        "system": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
            "disk_total_gb": psutil.disk_usage('/').total / 1024 / 1024 / 1024
        }
    }
    
    return status_info

@app.post("/test", summary="测试代理和浏览器功能", status_code=200)
async def test_endpoint(token: str = Depends(verify_token)):
    """
    测试代理和浏览器功能是否正常工作。
    会尝试访问一个简单的测试页面并返回结果。
    """
    test_url = "https://httpbin.org/ip"
    proxy_config = get_random_proxy_config()
    
    try:
        async with async_playwright() as p:
            # 启动浏览器
            launch_options = {
                "headless": True,
                "timeout": 30000,
                "args": _get_optimized_browser_args()
            }
            
            if proxy_config:
                launch_options["proxy"] = proxy_config
                logging.info(f"使用代理测试: {proxy_config.get('server', '未知')}")
            
            browser = await _launch_browser_with_fallback(p, launch_options)
            
            try:
                page = await browser.new_page()
                page.set_default_navigation_timeout(30000)
                
                # 访问测试页面
                response = await page.goto(test_url, wait_until='domcontentloaded')
                
                if response and response.ok:
                    # 获取页面内容
                    content = await page.text_content('body')
                    
                    # 尝试解析JSON
                    try:
                        import json
                        ip_info = json.loads(content)
                        test_result = {
                            "status": "success",
                            "message": "代理和浏览器功能正常",
                            "test_url": test_url,
                            "response_status": response.status,
                            "ip_info": ip_info,
                            "proxy_used": proxy_config is not None,
                            "proxy_server": proxy_config.get('server') if proxy_config else None
                        }
                    except json.JSONDecodeError:
                        test_result = {
                            "status": "partial_success",
                            "message": "页面访问成功但内容解析失败",
                            "test_url": test_url,
                            "response_status": response.status,
                            "raw_content": content[:500] + "..." if len(content) > 500 else content,
                            "proxy_used": proxy_config is not None
                        }
                else:
                    test_result = {
                        "status": "failed",
                        "message": f"页面访问失败，状态码: {response.status if response else 'unknown'}",
                        "test_url": test_url,
                        "proxy_used": proxy_config is not None
                    }
                    
            finally:
                await browser.close()
                
    except Exception as e:
        test_result = {
            "status": "error",
            "message": f"测试过程中发生错误: {str(e)}",
            "error_type": type(e).__name__,
            "test_url": test_url,
            "proxy_used": proxy_config is not None
        }
    
    return test_result

@app.get("/debug/files", summary="获取调试文件列表", status_code=200)
async def get_debug_files(token: str = Depends(verify_token)):
    """
    获取可用的调试文件列表
    """
    import os
    import glob
    
    debug_files = []
    debug_dir = "/tmp/"
    
    # 查找调试文件
    patterns = [
        "page_*.png",
        "page_*.html",
        "*.png",
        "*.html"
    ]
    
    for pattern in patterns:
        files = glob.glob(os.path.join(debug_dir, pattern))
        for file_path in files:
            if os.path.exists(file_path):
                file_info = {
                    "name": os.path.basename(file_path),
                    "path": file_path,
                    "size": os.path.getsize(file_path),
                    "modified": os.path.getmtime(file_path)
                }
                debug_files.append(file_info)
    
    return {
        "debug_files": debug_files,
        "total_files": len(debug_files),
        "debug_directory": debug_dir
    }

@app.get("/debug/download/{filename}", summary="下载调试文件")
async def download_debug_file(filename: str, token: str = Depends(verify_token)):
    """
    下载指定的调试文件
    """
    import os
    from fastapi.responses import FileResponse
    
    # 安全检查：只允许下载特定类型的文件
    allowed_extensions = ['.png', '.html', '.txt', '.log']
    file_ext = os.path.splitext(filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="不允许下载此类型的文件")
    
    file_path = os.path.join("/tmp/", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/octet-stream'
    )

@app.post("/get_menu", summary="获取iFood店铺菜单", status_code=200)
async def get_menu_endpoint(request: StoreRequest, token: str = Depends(verify_token)):
    """
    接收一个iFood店铺的web URL，返回其菜单的JSON数据。

    - **url**: iFood店铺的完整URL。
    - **需要认证**: 请求头中必须包含 'Authorization: Bearer your-super-secret-token'。
    """
    # 添加人类行为模拟延迟
    delay = get_human_like_delay()
    logging.info(f"模拟人类行为，等待 {delay:.2f} 秒...")
    await asyncio.sleep(delay)
    
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
    # 添加人类行为模拟延迟
    delay = get_human_like_delay()
    logging.info(f"模拟人类行为，等待 {delay:.2f} 秒...")
    await asyncio.sleep(delay)
    
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
    # 添加人类行为模拟延迟
    delay = get_human_like_delay()
    logging.info(f"模拟人类行为，等待 {delay:.2f} 秒...")
    await asyncio.sleep(delay)
    
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

# --- 主程序入口点 ---
if __name__ == "__main__":
    import uvicorn
    
    # 配置服务器参数
    host = "0.0.0.0"
    port = 8000
    reload = True
    
    print(f"🚀 启动 iFood Menu API 服务器...")
    print(f"📍 服务器地址: http://{host}:{port}")
    print(f"📚 API 文档: http://{host}:{port}/docs")
    print(f"🔑 认证令牌: {API_TOKEN}")
    print(f"🌐 代理策略: {PROXY_ROTATION_STRATEGY}")
    print(f"☁️  Cloud Function 模式: {IS_CLOUD_FUNCTION}")
    
    if IS_CLOUD_FUNCTION:
        print(f"🌍 GCP 区域: {GCP_REGION}")
        print(f"🔄 GCP IP 轮换: {USE_GCP_NATURAL_IP_ROTATION}")
    
    # 启动服务器
    uvicorn.run(
        "api:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
