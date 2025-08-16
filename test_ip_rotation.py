#!/usr/bin/env python3
"""
测试Cloud Run的IP轮换效果
通过多次调用API，记录不同的出口IP地址
"""

import requests
import time
import json
from collections import Counter

def test_ip_rotation(cloud_run_url, api_token, num_requests=20):
    """
    测试IP轮换效果
    """
    print(f"🧪 开始测试IP轮换效果 (请求次数: {num_requests})")
    
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    
    # 使用测试端点获取当前IP
    test_data = {"test": True}
    
    ips = []
    successful_requests = 0
    
    for i in range(num_requests):
        try:
            print(f"📡 第 {i+1}/{num_requests} 次请求...")
            
            # 调用测试API
            response = requests.post(
                f"{cloud_run_url}/test",
                headers=headers,
                json=test_data,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # 尝试从响应中获取IP信息
                # 这需要API返回当前的出口IP
                current_ip = data.get("client_ip", "unknown")
                ips.append(current_ip)
                successful_requests += 1
                
                print(f"  ✅ 成功 - IP: {current_ip}")
            else:
                print(f"  ❌ 失败 - 状态码: {response.status_code}")
            
            # 等待一段时间，让Cloud Run有机会切换实例
            time.sleep(2)
            
        except Exception as e:
            print(f"  ❌ 错误: {e}")
    
    # 分析结果
    print("\n📊 测试结果分析:")
    print(f"成功请求: {successful_requests}/{num_requests}")
    
    if ips:
        ip_counts = Counter(ips)
        unique_ips = len(ip_counts)
        
        print(f"发现的唯一IP数量: {unique_ips}")
        print(f"IP分布情况:")
        
        for ip, count in ip_counts.most_common():
            percentage = (count / len(ips)) * 100
            print(f"  {ip}: {count}次 ({percentage:.1f}%)")
        
        # IP轮换效果评估
        if unique_ips >= num_requests * 0.7:
            print("🎉 IP轮换效果: 优秀 (>70%)")
        elif unique_ips >= num_requests * 0.4:
            print("👍 IP轮换效果: 良好 (40-70%)")
        elif unique_ips >= num_requests * 0.2:
            print("⚠️ IP轮换效果: 一般 (20-40%)")
        else:
            print("❌ IP轮换效果: 较差 (<20%)")

if __name__ == "__main__":
    # 配置你的Cloud Run URL和API Token
    CLOUD_RUN_URL = "https://your-service-url"  # 替换为实际URL
    API_TOKEN = "local-dev-token"  # 替换为实际token
    
    test_ip_rotation(CLOUD_RUN_URL, API_TOKEN, 20)
