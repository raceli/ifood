# -*- coding: utf-8 -*-
"""
高级反检测配置模块
针对iFood等大型网站的反爬策略进行专门优化
"""

import random
from typing import Dict, List, Any
from dataclasses import dataclass

@dataclass
class StealthConfig:
    """隐身配置类"""
    viewport_width: int
    viewport_height: int
    user_agent: str
    screen_resolution: str
    timezone: str
    language: str
    platform: str
    memory: int  # GB
    cpu_cores: int

def get_stealth_browser_args() -> List[str]:
    """
    获取增强的反检测浏览器参数
    模拟真实用户环境，避免常见的自动化检测
    """
    base_args = [
        # 基本沙箱设置
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        
        # 禁用自动化检测特征
        "--disable-blink-features=AutomationControlled",  # 重要：禁用自动化控制特征
        "--disable-features=VizDisplayCompositor",
        "--disable-extensions-http-throttling",
        
        # 模拟真实用户行为
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-features=TranslateUI",
        
        # 网络和性能优化
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-ipc-flooding-protection",
        
        # 隐私和安全
        "--no-first-run",
        "--no-pings",
        "--no-zygote",
        "--disable-sync",
        "--disable-background-networking",
        
        # 内存优化
        "--memory-pressure-off",
        "--max_old_space_size=4096",
        
        # 关闭不需要的功能
        "--disable-client-side-phishing-detection",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-features=AudioServiceOutOfProcess",
        
        # 自定义用户数据目录（避免检测）
        f"--user-data-dir=/tmp/chrome-user-data-{random.randint(10000, 99999)}",
        
        # GPU设置
        "--disable-gpu",
        "--disable-software-rasterizer",
        
        # 窗口设置
        "--hide-scrollbars",
        "--mute-audio",
        
        # 重要：禁用webdriver特征
        "--disable-web-security",
        "--disable-features=VizDisplayCompositor,VizHitTestSurfaceLayer",
        
        # 模拟真实屏幕
        f"--window-size={random.choice(['1920,1080', '1366,768', '1440,900', '1536,864'])}",
    ]
    
    return base_args

def get_random_stealth_config() -> StealthConfig:
    """获取随机的隐身配置"""
    configs = [
        # Windows 10 配置
        StealthConfig(
            viewport_width=1920,
            viewport_height=1080,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            screen_resolution="1920x1080",
            timezone="America/Sao_Paulo",
            language="pt-BR,pt;q=0.9,en;q=0.8",
            platform="Win32",
            memory=8,
            cpu_cores=8
        ),
        # Windows 11 配置
        StealthConfig(
            viewport_width=1366,
            viewport_height=768,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            screen_resolution="1366x768",
            timezone="America/Sao_Paulo",
            language="pt-BR,pt;q=0.9,en;q=0.8",
            platform="Win32",
            memory=16,
            cpu_cores=4
        ),
        # macOS 配置
        StealthConfig(
            viewport_width=1440,
            viewport_height=900,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            screen_resolution="1440x900",
            timezone="America/Sao_Paulo",
            language="pt-BR,pt;q=0.9,en;q=0.8",
            platform="MacIntel",
            memory=16,
            cpu_cores=8
        )
    ]
    
    return random.choice(configs)

def get_stealth_page_scripts() -> List[str]:
    """
    获取需要在页面中执行的反检测脚本
    """
    scripts = [
        # 移除webdriver特征
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        """,
        
        # 伪造Chrome运行时
        """
        window.chrome = {
            runtime: {},
        };
        """,
        
        # 伪造权限API
        """
        Object.defineProperty(navigator, 'permissions', {
            get: () => ({
                query: () => Promise.resolve({state: 'granted'}),
            }),
        });
        """,
        
        # 伪造插件信息
        """
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        """,
        
        # 伪造语言信息
        """
        Object.defineProperty(navigator, 'languages', {
            get: () => ['pt-BR', 'pt', 'en'],
        });
        """,
        
        # 移除自动化特征
        """
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        """
    ]
    
    return scripts

def get_realistic_headers() -> Dict[str, str]:
    """获取真实的HTTP请求头"""
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }

# 请求时间控制
def get_random_delay() -> float:
    """获取随机延迟时间（秒）"""
    return random.uniform(2.0, 8.0)

def get_human_like_delay() -> float:
    """获取类人类的延迟时间"""
    delays = [
        random.uniform(1.5, 3.0),  # 快速用户 - 30%
        random.uniform(3.0, 6.0),  # 正常用户 - 50%
        random.uniform(6.0, 12.0), # 慢速用户 - 20%
    ]
    weights = [0.3, 0.5, 0.2]
    return random.choices(delays, weights=weights)[0]
