import asyncio
import logging
import os
import json
import time
import random
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError
from typing import Dict, Any, Optional
import aiohttp
from fake_useragent import UserAgent, FakeUserAgentError

# --- 配置 ---
API_TOKEN = os.getenv("API_TOKEN", "local-dev-token")
IS_CLOUD_FUNCTION = os.getenv("FUNCTION_TARGET") is not None

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

# --- FastAPI 应用实例 ---
app = FastAPI(
    title="iFood Proxy Service",
    description="一个在Cloud Function上运行的代理服务，为K8s服务提供iFood网页访问能力",
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
class ProxyRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    data: Optional[Dict[str, Any]] = None
    timeout: int = 30
    wait_for_selector: Optional[str] = None
    wait_for_timeout: Optional[int] = None
    screenshot: bool = False
    extract_text: bool = False
    extract_html: bool = False

class ProxyResponse(BaseModel):
    status_code: int
    headers: Dict[str, str]
    content: str
    screenshot: Optional[str] = None
    text_content: Optional[str] = None
    html_content: Optional[str] = None
    execution_time: float

# --- 浏览器管理 ---
class BrowserManager:
    def __init__(self):
        self.browser = None
        self.page = None
        self._lock = asyncio.Lock()
    
    async def get_browser(self):
        """获取或创建浏览器实例"""
        async with self._lock:
            if self.browser is None or not self.browser.is_connected():
                await self._create_browser()
            return self.browser
    
    async def get_page(self):
        """获取或创建页面实例"""
        browser = await self.get_browser()
        if self.page is None or self.page.is_closed():
            self.page = await browser.new_page()
        return self.page
    
    async def _create_browser(self):
        """创建浏览器实例"""
        async with async_playwright() as p:
            # 尝试多种启动策略
            strategies = [
                {
                    "name": "标准启动",
                    "options": {
                        "headless": True,
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
                    "name": "系统浏览器查找",
                    "options": None
                }
            ]
            
            last_error = None
            for strategy in strategies:
                try:
                    logging.info(f"尝试{strategy['name']}...")
                    
                    if strategy["name"] == "系统浏览器查找":
                        # 动态查找系统浏览器
                        import subprocess
                        import os
                        
                        possible_browsers = [
                            "/usr/bin/google-chrome-stable",
                            "/usr/bin/chromium-browser",
                            "/usr/bin/chromium",
                            "/usr/bin/google-chrome"
                        ]
                        
                        found_browser = None
                        for browser_path in possible_browsers:
                            if os.path.exists(browser_path):
                                found_browser = browser_path
                                break
                        
                        if found_browser:
                            self.browser = await p.chromium.launch(
                                headless=True,
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
                            raise Exception("未找到系统浏览器")
                    else:
                        self.browser = await p.chromium.launch(**strategy["options"])
                    
                    logging.info(f"{strategy['name']}成功")
                    break
                    
                except Exception as e:
                    last_error = e
                    logging.warning(f"{strategy['name']}失败: {str(e)}")
                    continue
            
            if self.browser is None:
                raise Exception(f"无法启动浏览器，最后错误: {str(last_error)}")
    
    async def close(self):
        """关闭浏览器"""
        if self.browser and self.browser.is_connected():
            await self.browser.close()
            self.browser = None
            self.page = None

# 全局浏览器管理器
browser_manager = BrowserManager()

# --- 代理服务核心逻辑 ---
async def proxy_request(request: ProxyRequest) -> ProxyResponse:
    """处理代理请求"""
    start_time = time.time()
    
    try:
        page = await browser_manager.get_page()
        
        # 设置User-Agent
        user_agent = get_random_user_agent()
        await page.set_extra_http_headers({
            "User-Agent": user_agent,
            **(request.headers or {})
        })
        
        # 设置超时
        page.set_default_timeout(request.timeout * 1000)
        
        logging.info(f"正在访问: {request.url}")
        
        # 导航到页面
        if request.method.upper() == "GET":
            response = await page.goto(request.url, wait_until='domcontentloaded')
        else:
            # 对于POST请求，先导航到页面，然后执行POST
            await page.goto(request.url, wait_until='domcontentloaded')
            if request.data:
                # 这里需要根据具体需求实现POST逻辑
                response = await page.evaluate(f"""
                    fetch('{request.url}', {{
                        method: '{request.method}',
                        headers: {json.dumps(request.headers or {})},
                        body: {json.dumps(request.data)}
                    }})
                """)
            else:
                response = await page.reload()
        
        # 等待特定元素（如果指定）
        if request.wait_for_selector:
            await page.wait_for_selector(request.wait_for_selector, timeout=request.wait_for_timeout or 10000)
        
        # 等待指定时间（如果指定）
        if request.wait_for_timeout:
            await page.wait_for_timeout(request.wait_for_timeout)
        
        # 获取页面内容
        content = await page.content()
        
        # 获取响应头
        headers = {}
        if hasattr(response, 'headers'):
            headers = dict(response.headers)
        
        # 获取状态码
        status_code = response.status if hasattr(response, 'status') else 200
        
        # 截图（如果需要）
        screenshot_data = None
        if request.screenshot:
            screenshot_bytes = await page.screenshot()
            import base64
            screenshot_data = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        # 提取文本内容（如果需要）
        text_content = None
        if request.extract_text:
            text_content = await page.text_content('body')
        
        # 提取HTML内容（如果需要）
        html_content = None
        if request.extract_html:
            html_content = await page.content()
        
        execution_time = time.time() - start_time
        
        return ProxyResponse(
            status_code=status_code,
            headers=headers,
            content=content,
            screenshot=screenshot_data,
            text_content=text_content,
            html_content=html_content,
            execution_time=execution_time
        )
        
    except Exception as e:
        execution_time = time.time() - start_time
        logging.error(f"代理请求失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "ProxyError",
                "message": str(e),
                "execution_time": execution_time
            }
        )

# --- API 端点 ---
@app.get("/health", summary="健康检查")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "iFood Proxy Service",
        "timestamp": time.time(),
        "is_cloud_function": IS_CLOUD_FUNCTION
    }

@app.post("/proxy", summary="代理请求", response_model=ProxyResponse)
async def proxy_endpoint(request: ProxyRequest):
    """
    代理请求端点
    
    - **url**: 要访问的URL
    - **method**: HTTP方法 (GET/POST)
    - **headers**: 请求头
    - **data**: POST数据
    - **timeout**: 超时时间（秒）
    - **wait_for_selector**: 等待的CSS选择器
    - **wait_for_timeout**: 等待时间（毫秒）
    - **screenshot**: 是否截图
    - **extract_text**: 是否提取文本
    - **extract_html**: 是否提取HTML
    """
    try:
        return await proxy_request(request)
    except Exception as e:
        logging.error(f"代理端点错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/simple", summary="简单代理请求")
async def simple_proxy(request: ProxyRequest):
    """
    简单代理请求，只返回页面内容
    """
    try:
        result = await proxy_request(request)
        return {
            "status": "success",
            "status_code": result.status_code,
            "content": result.content,
            "execution_time": result.execution_time
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "execution_time": time.time()
        }

# --- 清理函数 ---
@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理资源"""
    await browser_manager.close()

# --- 测试端点 ---
@app.get("/test", summary="测试端点")
async def test_endpoint():
    """测试端点，访问iFood主页"""
    test_request = ProxyRequest(
        url="https://www.ifood.com.br",
        method="GET",
        timeout=30,
        extract_text=True
    )
    
    try:
        result = await proxy_request(test_request)
        return {
            "status": "success",
            "title": "iFood Proxy Service Test",
            "page_status": result.status_code,
            "content_length": len(result.content),
            "execution_time": result.execution_time,
            "text_preview": result.text_content[:200] if result.text_content else None
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080) 