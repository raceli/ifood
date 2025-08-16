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
    1. 在Cloud Function环境中，优先使用GCP自然IP轮换
    2. 使用智能代理管理器选择最佳代理
    3. 如果配置了云代理，使用云代理
    4. 最后直接连接
    
    返回Playwright格式的代理配置字典。
    """
    # 1. 在Cloud Function环境中，优先使用GCP自然IP轮换
    if IS_CLOUD_FUNCTION and USE_GCP_NATURAL_IP_ROTATION:
        logging.info("在Cloud Function环境中，使用GCP自然IP轮换")
        return None  # 返回None表示不使用代理，让GCP自动分配IP
    
    # 2. 优先使用智能代理管理器
    smart_proxy = get_smart_proxy_config()
    if smart_proxy:
        logging.info(f"使用智能代理管理器选择的代理: {smart_proxy.get('server', 'unknown')}")
        return smart_proxy
    
    # 3. 回退到云代理
    cloud_proxy = get_cloud_proxy_config()
    if cloud_proxy:
        logging.info("使用云代理配置")
        return cloud_proxy
    
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
    针对Cloud Function环境进行了优化，参考 Browserless 最佳实践。
    """
    async with async_playwright() as p:
        browser = None
        try:
            # 根据 Browserless 建议，为 Cloud Function 优化启动配置
            launch_options = {
                "headless": True,
                "timeout": 30000,  # 30秒启动超时
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
            
            # 注入反检测脚本
            for script in get_stealth_page_scripts():
                await page.add_init_script(script)
            
            # 设置页面超时和错误处理
            page.set_default_navigation_timeout(45000)  # 45秒导航超时
            page.set_default_timeout(30000)  # 30秒默认超时
            
            # 可选：如果不需要图片，可以阻止图片请求以提高性能
            if IS_CLOUD_FUNCTION:
                await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico}", lambda route: route.abort())
                await page.route("**/*.{css}", lambda route: route.abort())  # 可选：阻止CSS以提高速度
            
            logging.info(f"正在导航到: {target_url}")

            # 记录开始时间（用于计算响应时间）
            start_time = time.time()

            # 设置更合理的超时时间
            response_awaitables = [
                page.wait_for_event(
                    "response",
                    lambda res, p=pattern: p.search(res.url),
                    timeout=35000  # 增加超时时间
                )
                for pattern in api_patterns.values()
            ]
            navigation_awaitable = page.goto(
                target_url, 
                wait_until='domcontentloaded', 
                timeout=30000  # 增加导航超时时间
            )
            
            all_results = await asyncio.gather(
                *response_awaitables, navigation_awaitable, return_exceptions=True
            )
            
            # 计算响应时间
            response_time = time.time() - start_time
            
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
            
            # 检查请求是否成功
            has_success = any("error" not in result for result in processed_results_list if isinstance(result, dict))
            
            # 记录代理使用结果
            if has_success:
                record_proxy_result(proxy_config, True, response_time)
            else:
                record_proxy_result(proxy_config, False, response_time, "all_apis_failed")
            
            return dict(zip(api_keys, processed_results_list))

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
                "cloud_proxy_configured": bool(CLOUD_PROXY_HOST),
                "local_proxy_file_exists": os.path.exists(PROXY_FILE)
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
        "proxy_manager_stats": proxy_stats,
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
