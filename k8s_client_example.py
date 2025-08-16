#!/usr/bin/env python3
"""
K8s 客户端示例
展示如何通过 Cloud Function 代理服务访问 iFood 网页
"""

import requests
import json
import time
from typing import Dict, Any, Optional

class IFoodProxyClient:
    """iFood 代理客户端"""
    
    def __init__(self, proxy_base_url: str):
        """
        初始化代理客户端
        
        Args:
            proxy_base_url: 代理服务的基础URL，例如：
                https://us-central1-aisalesagent-461308.cloudfunctions.net/ifood-proxy
        """
        self.proxy_base_url = proxy_base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'IFoodProxyClient/1.0'
        })
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        url = f"{self.proxy_base_url}-health"
        response = self.session.get(url)
        return response.json()
    
    def test_proxy(self) -> Dict[str, Any]:
        """测试代理服务"""
        url = f"{self.proxy_base_url}-test"
        response = self.session.get(url)
        return response.json()
    
    def simple_proxy(self, target_url: str, **kwargs) -> Dict[str, Any]:
        """
        简单代理请求
        
        Args:
            target_url: 目标URL
            **kwargs: 其他参数 (timeout, headers, data等)
        """
        url = f"{self.proxy_base_url}-simple"
        payload = {
            "url": target_url,
            **kwargs
        }
        response = self.session.post(url, json=payload)
        return response.json()
    
    def full_proxy(self, target_url: str, **kwargs) -> Dict[str, Any]:
        """
        完整代理请求
        
        Args:
            target_url: 目标URL
            **kwargs: 其他参数
        """
        url = f"{self.proxy_base_url}-proxy"
        payload = {
            "url": target_url,
            **kwargs
        }
        response = self.session.post(url, json=payload)
        return response.json()
    
    def get_ifood_menu(self, restaurant_url: str) -> Dict[str, Any]:
        """
        获取 iFood 餐厅菜单
        
        Args:
            restaurant_url: iFood 餐厅页面URL
        """
        return self.full_proxy(
            url=restaurant_url,
            method="GET",
            timeout=60,
            wait_for_selector='h2[class*="restaurant-menu__category-title"]',
            extract_text=True,
            extract_html=True
        )
    
    def get_ifood_shop_info(self, restaurant_url: str) -> Dict[str, Any]:
        """
        获取 iFood 餐厅信息
        
        Args:
            restaurant_url: iFood 餐厅页面URL
        """
        return self.full_proxy(
            url=restaurant_url,
            method="GET",
            timeout=30,
            extract_text=True
        )

def main():
    """主函数示例"""
    
    # 配置代理服务URL (需要替换为实际的URL)
    PROXY_BASE_URL = "https://us-central1-aisalesagent-461308.cloudfunctions.net/ifood-proxy"
    
    # 创建客户端
    client = IFoodProxyClient(PROXY_BASE_URL)
    
    print("🚀 iFood 代理客户端示例")
    print("=" * 50)
    
    # 1. 健康检查
    print("\n1. 健康检查...")
    try:
        health = client.health_check()
        print(f"✅ 健康状态: {health}")
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return
    
    # 2. 测试代理服务
    print("\n2. 测试代理服务...")
    try:
        test_result = client.test_proxy()
        print(f"✅ 测试结果: {test_result}")
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return
    
    # 3. 简单代理请求
    print("\n3. 简单代理请求...")
    try:
        simple_result = client.simple_proxy("https://www.ifood.com.br")
        print(f"✅ 简单代理成功，状态码: {simple_result.get('status_code')}")
        print(f"   执行时间: {simple_result.get('execution_time', 0):.2f}秒")
    except Exception as e:
        print(f"❌ 简单代理失败: {e}")
    
    # 4. 获取餐厅菜单
    print("\n4. 获取餐厅菜单...")
    restaurant_url = "https://www.ifood.com.br/delivery/sao-paulo-sp/pizza-prime---bela-vista-jardim-paulista/6d58c6a1-5d86-4b5c-823f-07e23479c83f"
    
    try:
        menu_result = client.get_ifood_menu(restaurant_url)
        print(f"✅ 菜单获取成功，状态码: {menu_result.get('status_code')}")
        print(f"   执行时间: {menu_result.get('execution_time', 0):.2f}秒")
        
        # 提取一些基本信息
        if menu_result.get('text_content'):
            text = menu_result['text_content']
            print(f"   页面文本长度: {len(text)} 字符")
            print(f"   页面预览: {text[:200]}...")
        
    except Exception as e:
        print(f"❌ 菜单获取失败: {e}")
    
    print("\n🎯 示例完成！")

if __name__ == "__main__":
    main() 