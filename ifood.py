import json
from playwright.sync_api import sync_playwright, TimeoutError
from bs4 import BeautifulSoup
import time
import random # 导入random模块
import re

def format_price_to_integer(price_str: str) -> int:
    """
    将价格字符串（例如 "R$ 47,50" 或 "+ R$ 19,00"）清理并转换为以"分"为单位的整数（例如 4750 或 1900）。
    能处理加号、货币符号和巴西的数字格式。
    如果价格字符串为空或无效，则返回 0。
    """
    if not isinstance(price_str, str) or not price_str.strip():
        return 0
    
    # 1. 移除货币符号、加号和所有空格
    cleaned_str = price_str.replace("R$", "").replace("+", "").strip()

    # 2. 在巴西格式中，'.'是千位分隔符（如果有的话），','是小数分隔符。
    # 我们需要移除'.'，并将','替换为'.'，以便转换为浮点数。
    cleaned_str = cleaned_str.replace('.', '').replace(',', '.')

    # 3. 转换为浮点数，乘以100得到"分"，然后取整
    try:
        price_float = float(cleaned_str)
        return int(price_float * 100)
    except ValueError:
        return 0

# --- 1. 在这里配置你的SOCKS5代理信息 ---
PROXY_HOST = "127.0.0.1"  # 你的SOCKS5代理服务器IP或域名
PROXY_PORT = 7897         # 你的SOCKS5代理端口 (例如，Tor通常是9050)
PROXY_USER = ""           # 你的代理用户名，如果没有则留空
PROXY_PASS = ""           # 你的代理密码，如果没有则留空

# --- 准备Playwright的代理配置字典 ---
proxy_settings = {
    "server": f"socks5://{PROXY_HOST}:{PROXY_PORT}"
}
if PROXY_USER and PROXY_PASS:
    proxy_settings["username"] = PROXY_USER
    proxy_settings["password"] = PROXY_PASS


def check_ip_with_proxy(playwright_instance, proxy_config: dict):
    """
    一个辅助函数，用于启动一个带代理的浏览器，访问IP查询网站，
    并打印出当前的出口IP，以验证代理是否工作。
    """
    print("--- 正在验证代理设置 ---")
    ip_check_url = "https://httpbin.org/ip"
    try:
        browser = playwright_instance.chromium.launch(headless=True, proxy=proxy_config)
        page = browser.new_page()
        page.goto(ip_check_url, timeout=20000)
        content = page.inner_text('body')
        ip_data = json.loads(content)
        print(f"✅ 代理验证成功！当前出口 IP: {ip_data['origin']}")
        browser.close()
        return True
    except Exception as e:
        print(f"❌ 代理验证失败。请检查你的代理服务器地址、端口、认证信息是否正确且代理服务正在运行。")
        print(f"错误详情: {e}")
        return False


def extract_ifood_menu(url: str, proxy_config: dict) -> list:
    """
    使用Playwright和BeautifulSoup从iFood餐厅页面提取完整的菜单结构，并通过指定的代理访问。
    此版本会交互式点击每个菜品，以获取详情弹窗中的高清大图。

    :param url: iFood餐厅页面的URL
    :param proxy_config: Playwright的代理配置字典
    :return: 一个包含菜单信息的列表。
    """
    with sync_playwright() as p:
        print("\n正在通过代理启动浏览器...")
        browser = p.chromium.launch(
            headless=False,
            proxy=proxy_config,
            args=["--start-maximized"]
        )
        page = browser.new_page()
        
        try:
            print(f"正在通过代理访问页面: {url}")
            page.goto(url, wait_until='networkidle', timeout=90000)

            try:
                print("正在查找地址弹出窗口并尝试点击'Ignorar'按钮...")
                ignore_button_selector = '[data-test-id="hint-left-button"]'
                page.wait_for_selector(ignore_button_selector, timeout=20000)
                page.click(ignore_button_selector)
                print("✅ 成功点击'Ignorar'按钮。")
            except Exception as e:
                print(f"🟡 未找到或未能点击'Ignorar'按钮（可能弹窗未出现）: {e}")

            print("等待菜单动态加载...")
            page.wait_for_selector(
                'h2[class*="restaurant-menu__category-title"], h2[class*="restaurant-menu-group__title"]',
                timeout=60000
            )

            print("正在模仿人类行为滚动页面以加载所有内容...")
            last_height = page.evaluate("document.body.scrollHeight")
            while True:
                scroll_distance = random.randint(500, 1000)
                page.evaluate(f"window.scrollBy(0, {scroll_distance});")
                time.sleep(random.uniform(0.8, 1.8))
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                    if page.evaluate("document.body.scrollHeight") == last_height:
                        print("✅ 已滚动到页面底部。")
                        break
                last_height = new_height

            print("页面加载完成，开始使用Playwright进行动态交互和数据提取...")

            dish_card_locator = page.locator('div[class*="dish-card-wrapper"], li[class*="dish-list-item"]')
            dish_count = dish_card_locator.count()
            print(f"在页面上动态找到了 {dish_count} 个菜品卡片。")

            if dish_count == 0:
                print("❌ 错误: 页面上未能定位到任何菜品卡片。")
                page.screenshot(path="ifood_error_no_dishes_found.png")
                print("已保存截图用于调试: ifood_error_no_dishes_found.png")
                return []
            
            menu_data = [] # 最终的数据将存放在这里

            for i in range(dish_count):
                dish_card = dish_card_locator.nth(i)
                
                # --- 提取菜品基本信息 ---
                name_element = dish_card.locator('h3[class*="dish-card__description"]')
                desc_element = dish_card.locator('p[class*="dish-card__details"]')
                thumb_element = dish_card.locator('img[class*="dish-card__image"]')

                name = name_element.inner_text() if name_element.count() > 0 else f"菜品 #{i+1}"
                description = desc_element.inner_text() if desc_element.count() > 0 else ""
                thumbnail_url = thumb_element.get_attribute('src') if thumb_element.count() > 0 else ""

                # --- 全新的、更全面的价格提取逻辑 (价格转为整数分) ---
                price = 0
                original_price = 0 # 仅当有折扣时才存在

                discount_price_element = dish_card.locator('span[class*="dish-card__price--discount"]')
                original_price_element = dish_card.locator('span[class*="dish-card__price--original"]')

                if discount_price_element.count() > 0:
                    # 这是个折扣商品
                    original_price_text = ""
                    if original_price_element.count() > 0:
                        original_price_text = original_price_element.inner_text()
                        original_price = format_price_to_integer(original_price_text)

                    # 从混合文本中移除原价文本，得到纯净的折扣价文本
                    full_discount_text = discount_price_element.inner_text()
                    discount_price_text = full_discount_text.replace(original_price_text, "").strip()
                    price = format_price_to_integer(discount_price_text)
                else:
                    # 这是个普通价格商品
                    regular_price_element = dish_card.locator('span[data-test-id="dish-card-price"]')
                    if regular_price_element.count() > 0:
                        price = format_price_to_integer(regular_price_element.inner_text())

                print(f"\n--- 正在处理菜品 ({i+1}/{dish_count}): {name} ---")
                
                # 为弹窗内数据重置变量
                large_image_url = ""
                dish_options = []

                try:
                    print(f"    - 正在点击菜品...")
                    dish_card.click(timeout=10000)

                    modal_selector = 'div[role="dialog"]'
                    page.locator(modal_selector).wait_for(state="visible", timeout=10000)
                    print(f"    - 弹窗已出现，正在提取详细信息...")

                    # --- 从弹窗中提取更详细的描述 ---
                    modal_desc_element = page.locator(f'{modal_selector} p[data-test-id="dish-content__details"]')
                    if modal_desc_element.count() > 0:
                        modal_description = modal_desc_element.inner_text()
                        if modal_description and modal_description.strip():
                            print("    ✓ 已从弹窗中更新描述。")
                            description = modal_description.strip() # 更新描述

                    # 提取大图URL
                    # 优先尝试用alt属性匹配，如果不行，就找弹窗里最主要的那张图
                    image_locator = page.locator(f'{modal_selector} img[alt="{name}"]')
                    if image_locator.count() == 0:
                        image_locator = page.locator(f'{modal_selector} div[class*="image"] img').first
                    
                    if image_locator.count() > 0:
                        medium_res_url = image_locator.get_attribute('src')
                        if medium_res_url:
                            large_image_url = re.sub(r'/t_[^/]+/', '/', medium_res_url)
                            print(f"    ✓ 成功获取并处理为高清图URL。")
                        else:
                            large_image_url = ""
                            print(f"    - 警告: 找到图片标签但未能获取src属性。")
                    else:
                        print(f"    - 警告: 未能在弹窗中找到大图。")

                    # --- 全新的、双重布局兼容的选项抓取逻辑 ---
                    
                    # 布局 A: garnish-choices (基于用户反馈)
                    garnish_groups = page.locator(f'{modal_selector} section.garnish-choices__list')
                    if garnish_groups.count() > 0:
                        print(f"    - (布局A) 找到 {garnish_groups.count()} 个 'garnish-choices' 选项组。")
                        for group in garnish_groups.all():
                            title_element = group.locator('p.garnish-choices__title')
                            group_title = title_element.inner_text().split('\n')[0].strip()
                            limit_element = title_element.locator('span.garnish-choices__title-desc')
                            selection_limit = limit_element.inner_text() if limit_element.count() > 0 else ""

                            items_in_group = []
                            option_items = group.locator('label.garnish-choices__label')
                            for item in option_items.all():
                                name_element = item.locator('p.garnish-choices__option-desc')
                                # 使用更精确的图片选择器
                                image_element = item.locator('figure.garnish-choices__content-img img.garnish-choices__option-img')

                                full_name_text = name_element.inner_text() if name_element.count() > 0 else ""
                                
                                # 修正价格与名称的提取逻辑
                                price_element = name_element.locator('span.garnish-choices__option-price')
                                price_text = price_element.inner_text() if price_element.count() > 0 else ""
                                item_name = full_name_text.replace(price_text, "").strip() if price_text else full_name_text
                                item_price_int = format_price_to_integer(price_text)
                                
                                item_image_url = ""
                                if image_element.count() > 0:
                                    medium_res_url = image_element.get_attribute('src')
                                    if medium_res_url:
                                        item_image_url = re.sub(r'/t_[^/]+/', '/', medium_res_url)
                                else:
                                    # 增加一个调试日志
                                    print(f"        - (布局A) 警告: 在选项 '{item_name}' 中未找到图片元素。")

                                items_in_group.append({
                                    "name": item_name,
                                    "price": item_price_int,
                                    "image_url": item_image_url
                                })

                            dish_options.append({
                                "group_title": group_title,
                                "selection_limit": selection_limit,
                                "items": items_in_group
                            })
                    
                    # 布局 B: dish-complement (原始实现)
                    complement_groups = page.locator(f'{modal_selector} div[class*="dish-complement-group"]')
                    if complement_groups.count() > 0:
                        print(f"    - (布局B) 找到 {complement_groups.count()} 个 'dish-complement' 选项组。")
                        for group in complement_groups.all():
                            group_title_element = group.locator('h3[class*="dish-complement__title"]')
                            group_limit_element = group.locator('p[class*="dish-complement__limit"]')
                            group_title = group_title_element.inner_text() if group_title_element.count() > 0 else ""
                            selection_limit = group_limit_element.inner_text() if group_limit_element.count() > 0 else ""

                            items_in_group = []
                            option_items = group.locator('div[class*="dish-complement-item"]')
                            for item in option_items.all():
                                item_text = item.inner_text()
                                item_name, item_price = "", 0
                                if '+ R$' in item_text:
                                    parts = item_text.split('+ R$')
                                    item_name = parts[0].strip()
                                    # 格式化价格
                                    item_price = format_price_to_integer(f"R$ {parts[1].strip()}")
                                else:
                                    item_name = item_text.strip()
                                
                                items_in_group.append({"name": item_name, "price": item_price, "image_url": ""})

                            dish_options.append({
                                "group_title": group_title,
                                "selection_limit": selection_limit,
                                "items": items_in_group
                            })
                    
                    if dish_options:
                        print(f"    ✓ 成功抓取 {len(dish_options)} 个选项组。")
                    else:
                        print(f"    - 未在该弹窗中找到任何已知布局的选项组。")

                    print(f"    - 正在按 ESC 键关闭弹窗...")
                    page.keyboard.press("Escape")
                    page.locator(modal_selector).wait_for(state="hidden", timeout=5000)

                except Exception as e:
                    print(f"    - 错误: 在处理第 {i+1} 个菜品弹窗时失败: {e}")
                    page.keyboard.press("Escape") # 尝试恢复
                    time.sleep(1)

                menu_data.append({
                    "name": name,
                    "description": description,
                    "price": price,
                    "original_price": original_price,
                    "image_url": large_image_url,
                    "thumbnail_url": thumbnail_url,
                    "options": dish_options # 添加选项数据
                })
            
            print("\n✅ 所有菜品处理完毕。")
            return menu_data # 返回包含所有菜品信息的列表

        except TimeoutError:
            print("页面加载超时或未找到菜单元素。原因可能包括：")
            print("  - 代理服务器连接缓慢或不稳定。")
            print("  - 网站结构已更改或出现人机验证（如CAPTCHA）。")
            print("  - iFood可能屏蔽了您的代理IP。")
            screenshot_path = "ifood_error_screenshot.png"
            html_path = "ifood_error_page.html"
            page.screenshot(path=screenshot_path)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"❗ 已保存当前页面截图至: {screenshot_path}")
            print(f"❗ 已保存当前页面HTML至: {html_path}")
            return []
        except Exception as e:
            print(f"在抓取过程中发生未知错误: {e}")
            return []
        finally:
            print("关闭浏览器。")
            browser.close()

def save_to_json(data, filename="menu_data_proxy.json"):
    """将数据保存为JSON文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"\n菜单数据已成功保存到 {filename}")

def search_menu(menu_data, keyword):
    """在提取的菜单数据中搜索菜品"""
    results = []
    keyword_lower = keyword.lower()
    for dish in menu_data:
        if keyword_lower in dish['name'].lower() or keyword_lower in dish['description'].lower():
            results.append(dish)
    return results

# --- 主程序 ---
if __name__ == "__main__":
    # 推荐：先运行代理验证
    with sync_playwright() as p:
        if not check_ip_with_proxy(p, proxy_settings):
            print("由于代理验证失败，程序将退出。")
            exit() # 如果代理不通，直接退出，避免后续抓取失败

    # 代理验证通过后，开始抓取菜单
    target_url = "https://www.ifood.com.br/delivery/sao-paulo-sp/benjamin-a-padaria---conjunto-nacional-bela-vista/dc674b81-aba9-4435-bb98-70f11519af67"
    
    full_menu = extract_ifood_menu(target_url, proxy_settings)
    
    if full_menu:
        save_to_json(full_menu)

        print("\n--- 搜索演示 ---")
        search_term = "frango"
        print(f"\n搜索关键词: '{search_term}'")
        search_results = search_menu(full_menu, search_term)
        if search_results:
            for item in search_results:
                # 价格从整数"分"格式化回带货币符号的字符串用于显示
                price_info = f"价格: R$ {item['price']/100:.2f}".replace('.', ',')
                if item.get('original_price', 0) > 0:
                    price_info += f" (原价: R$ {item['original_price']/100:.2f})".replace('.', ',')
                print(f"  找到菜品: {item['name']} - {price_info}")
        else:
            print("  未找到相关菜品。")