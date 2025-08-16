# -*- coding: utf-8 -*-
"""
增强的代理管理模块
实现智能代理轮换、健康检查、失败重试等功能
"""

import asyncio
import random
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json

@dataclass
class ProxyStats:
    """代理统计信息"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_used: Optional[datetime] = None
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    average_response_time: float = 0.0
    is_blocked: bool = False
    blocked_until: Optional[datetime] = None
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    @property
    def is_healthy(self) -> bool:
        """检查代理是否健康"""
        if self.is_blocked and self.blocked_until:
            if datetime.now() > self.blocked_until:
                self.is_blocked = False
                self.blocked_until = None
                self.consecutive_failures = 0
                return True
            return False
        
        # 连续失败超过5次则认为不健康
        if self.consecutive_failures >= 5:
            return False
            
        # 成功率低于30%且使用过10次以上则认为不健康
        if self.total_requests > 10 and self.success_rate < 0.3:
            return False
            
        return True

@dataclass
class ProxyInfo:
    """代理信息"""
    host: str
    port: int
    username: str = ""
    password: str = ""
    proxy_type: str = "socks5"  # socks5, http, https
    stats: ProxyStats = field(default_factory=ProxyStats)
    
    @property
    def server_url(self) -> str:
        """代理服务器URL"""
        return f"{self.proxy_type}://{self.host}:{self.port}"
    
    def to_playwright_config(self) -> Dict[str, str]:
        """转换为Playwright配置格式"""
        config = {"server": self.server_url}
        if self.username and self.password:
            config["username"] = self.username
            config["password"] = self.password
        return config

class ProxyManager:
    """智能代理管理器"""
    
    def __init__(self, proxy_file: str = "proxies.txt"):
        self.proxy_file = proxy_file
        self.proxies: List[ProxyInfo] = []
        self.session_proxy: Optional[ProxyInfo] = None
        self.rotation_strategy = "smart"  # smart, random, round_robin, session
        self.current_index = 0
        self.logger = logging.getLogger(__name__)
        self.load_proxies()
    
    def load_proxies(self):
        """从文件加载代理列表"""
        try:
            with open(self.proxy_file, 'r', encoding='utf-8') as f:
                lines = f.read().strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                proxy_info = self._parse_proxy_line(line)
                if proxy_info:
                    self.proxies.append(proxy_info)
            
            self.logger.info(f"加载了 {len(self.proxies)} 个代理")
        except FileNotFoundError:
            self.logger.warning(f"代理文件 {self.proxy_file} 不存在")
        except Exception as e:
            self.logger.error(f"加载代理文件失败: {e}")
    
    def _parse_proxy_line(self, line: str) -> Optional[ProxyInfo]:
        """解析代理行"""
        try:
            # 支持格式：host:port 或 user:pass@host:port
            if '@' in line:
                auth, server = line.split('@', 1)
                username, password = auth.split(':', 1)
                host, port = server.split(':', 1)
            else:
                username, password = "", ""
                host, port = line.split(':', 1)
            
            return ProxyInfo(
                host=host.strip(),
                port=int(port.strip()),
                username=username.strip(),
                password=password.strip()
            )
        except Exception as e:
            self.logger.warning(f"解析代理行失败: {line}, 错误: {e}")
            return None
    
    def get_best_proxy(self) -> Optional[ProxyInfo]:
        """获取最佳代理"""
        if not self.proxies:
            return None
        
        if self.rotation_strategy == "session" and self.session_proxy:
            if self.session_proxy.stats.is_healthy:
                return self.session_proxy
            else:
                # 会话代理不健康，选择新的
                self.session_proxy = None
        
        healthy_proxies = [p for p in self.proxies if p.stats.is_healthy]
        
        if not healthy_proxies:
            self.logger.warning("没有健康的代理可用，将重置所有代理状态")
            self._reset_all_proxy_stats()
            healthy_proxies = self.proxies
        
        if self.rotation_strategy == "smart":
            return self._get_smart_proxy(healthy_proxies)
        elif self.rotation_strategy == "random":
            return random.choice(healthy_proxies)
        elif self.rotation_strategy == "round_robin":
            return self._get_round_robin_proxy(healthy_proxies)
        elif self.rotation_strategy == "session":
            self.session_proxy = self._get_smart_proxy(healthy_proxies)
            return self.session_proxy
        else:
            return random.choice(healthy_proxies)
    
    def _get_smart_proxy(self, proxies: List[ProxyInfo]) -> ProxyInfo:
        """智能选择代理（基于成功率、响应时间、使用频率）"""
        def score_proxy(proxy: ProxyInfo) -> float:
            stats = proxy.stats
            score = 0.0
            
            # 成功率权重 (40%)
            score += stats.success_rate * 0.4
            
            # 响应时间权重 (30%) - 越快越好
            if stats.average_response_time > 0:
                # 假设5秒是可接受的响应时间
                time_score = max(0, 1 - stats.average_response_time / 5.0)
                score += time_score * 0.3
            else:
                score += 0.3  # 没有历史数据，给予平均分
            
            # 使用频率权重 (20%) - 使用次数少的优先
            if stats.total_requests > 0:
                # 使用负权重，使用次数越少分数越高
                usage_score = max(0, 1 - stats.total_requests / 100.0)
                score += usage_score * 0.2
            else:
                score += 0.2  # 新代理优先使用
            
            # 最近使用时间权重 (10%) - 最近没用过的优先
            if stats.last_used:
                hours_since_use = (datetime.now() - stats.last_used).total_seconds() / 3600
                recent_score = min(1, hours_since_use / 24)  # 24小时内使用过的降权
                score += recent_score * 0.1
            else:
                score += 0.1  # 从未使用过的优先
            
            return score
        
        # 计算所有代理的分数并排序
        scored_proxies = [(score_proxy(p), p) for p in proxies]
        scored_proxies.sort(reverse=True, key=lambda x: x[0])
        
        # 从前30%中随机选择（避免总是选择同一个）
        top_count = max(1, len(scored_proxies) // 3)
        top_proxies = [p for _, p in scored_proxies[:top_count]]
        
        return random.choice(top_proxies)
    
    def _get_round_robin_proxy(self, proxies: List[ProxyInfo]) -> ProxyInfo:
        """轮询选择代理"""
        proxy = proxies[self.current_index % len(proxies)]
        self.current_index = (self.current_index + 1) % len(proxies)
        return proxy
    
    def record_success(self, proxy: ProxyInfo, response_time: float):
        """记录成功请求"""
        stats = proxy.stats
        stats.total_requests += 1
        stats.successful_requests += 1
        stats.last_used = datetime.now()
        stats.last_success = datetime.now()
        stats.consecutive_failures = 0
        
        # 更新平均响应时间
        if stats.average_response_time == 0:
            stats.average_response_time = response_time
        else:
            # 使用指数加权移动平均
            stats.average_response_time = (stats.average_response_time * 0.8 + response_time * 0.2)
        
        self.logger.debug(f"代理 {proxy.host}:{proxy.port} 请求成功，响应时间: {response_time:.2f}s")
    
    def record_failure(self, proxy: ProxyInfo, error_type: str = "unknown"):
        """记录失败请求"""
        stats = proxy.stats
        stats.total_requests += 1
        stats.failed_requests += 1
        stats.last_used = datetime.now()
        stats.consecutive_failures += 1
        
        # 如果连续失败次数过多，临时屏蔽代理
        if stats.consecutive_failures >= 3:
            stats.is_blocked = True
            # 屏蔽时间随失败次数增加
            block_minutes = min(60, stats.consecutive_failures * 5)
            stats.blocked_until = datetime.now() + timedelta(minutes=block_minutes)
            
            self.logger.warning(f"代理 {proxy.host}:{proxy.port} 连续失败 {stats.consecutive_failures} 次，"
                              f"临时屏蔽 {block_minutes} 分钟")
        
        self.logger.debug(f"代理 {proxy.host}:{proxy.port} 请求失败: {error_type}")
    
    def _reset_all_proxy_stats(self):
        """重置所有代理统计"""
        for proxy in self.proxies:
            proxy.stats.consecutive_failures = 0
            proxy.stats.is_blocked = False
            proxy.stats.blocked_until = None
        self.logger.info("已重置所有代理统计信息")
    
    def get_proxy_stats_summary(self) -> Dict:
        """获取代理统计摘要"""
        if not self.proxies:
            return {"total": 0, "healthy": 0, "blocked": 0}
        
        healthy = sum(1 for p in self.proxies if p.stats.is_healthy)
        blocked = sum(1 for p in self.proxies if p.stats.is_blocked)
        
        return {
            "total": len(self.proxies),
            "healthy": healthy,
            "blocked": blocked,
            "success_rate": sum(p.stats.success_rate for p in self.proxies) / len(self.proxies)
        }
    
    def set_rotation_strategy(self, strategy: str):
        """设置轮换策略"""
        if strategy in ["smart", "random", "round_robin", "session"]:
            self.rotation_strategy = strategy
            self.logger.info(f"代理轮换策略已设置为: {strategy}")
        else:
            self.logger.warning(f"无效的轮换策略: {strategy}")

# 全局代理管理器实例
proxy_manager = ProxyManager()

def get_smart_proxy_config() -> Optional[Dict[str, str]]:
    """获取智能选择的代理配置"""
    proxy = proxy_manager.get_best_proxy()
    if proxy:
        return proxy.to_playwright_config()
    return None

def record_proxy_result(proxy_config: Optional[Dict[str, str]], success: bool, response_time: float = 0.0, error_type: str = "unknown"):
    """记录代理使用结果"""
    if not proxy_config:
        return
    
    # 根据proxy_config找到对应的ProxyInfo
    server_url = proxy_config.get("server", "")
    for proxy in proxy_manager.proxies:
        if proxy.server_url == server_url:
            if success:
                proxy_manager.record_success(proxy, response_time)
            else:
                proxy_manager.record_failure(proxy, error_type)
            break
