# Cloud Functions 入口点
# 这个文件是 Google Cloud Functions 的必需入口点

from api import get_menu_endpoint, get_shop_info_endpoint, get_shop_all_endpoint

# 导出函数供 Cloud Functions 使用
__all__ = ['get_menu_endpoint', 'get_shop_info_endpoint', 'get_shop_all_endpoint'] 