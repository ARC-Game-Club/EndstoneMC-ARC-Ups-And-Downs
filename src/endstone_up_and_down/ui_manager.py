"""
UI管理器 - 处理所有股票插件的UI表单
"""
import json
from decimal import Decimal
import datetime
import time
from typing import Callable, Optional, TYPE_CHECKING

from endstone.form import ActionForm, ModalForm, Label, TextInput, Dropdown

if TYPE_CHECKING:
    from endstone_up_and_down.up_and_down_plugin import UpAndDownPlugin


class UIManager:
    def __init__(self, plugin):
        """
        初始化UI管理器
        :param plugin: 插件实例
        """
        self.plugin: "UpAndDownPlugin" = plugin

    def _resolve_online_player(self, xuid: str = "", name: str = "") -> Optional[object]:
        """从 online_players 重取活对象，避免对已销毁 Player 调用方法导致 purecall。"""
        xuid_s = str(xuid or "").strip()
        if xuid_s:
            for p in self.plugin.server.online_players or []:
                if str(getattr(p, "xuid", "")) == xuid_s:
                    return p
        name_s = str(name or "").strip()
        if name_s:
            try:
                return self.plugin.server.get_player(name_s)
            except Exception:
                return None
        return None

    def _run_for_player(self, player, fn: Callable, delay: int = 0):
        """调度仅对仍在线玩家执行的回调；闭包只存 xuid/name。"""
        xuid = str(getattr(player, "xuid", "") or "").strip()
        name = str(getattr(player, "name", "") or "").strip()

        def _wrapped() -> None:
            p = self._resolve_online_player(xuid, name)
            if p is None:
                return
            fn(p)

        return self.plugin.server.scheduler.run_task(self.plugin, _wrapped, delay=delay)
    
    # ==================== 主面板 ====================
    def show_main_panel(self, player):
        """显示股票插件主面板"""
        try:
            xuid = player.xuid
            
            # 检查账户是否已激活
            if not self.plugin.stock_dao.check_user_account(xuid):
                self._show_activate_account_panel(player)
                return
            
            # 使用线程加载数据
            import threading
            
            def load_data():
                try:
                    # 获取账户信息
                    balance = self.plugin.stock_dao.get_balance(xuid)

                    cached_player_data = self.plugin.stock_dao.get_cached_single_player_profit_loss(xuid)

                    # 合约占用（不拉价格，快速查询）
                    contract_count, contract_margin = self.plugin.stock_dao.get_open_margin_summary(xuid)

                    content = f"=== 股票账户概览(每30分钟更新) ===\n\n"
                    if cached_player_data != None:
                        total_market_value = cached_player_data['holdings_value']
                        total_wealth = cached_player_data['total_wealth']
                        relative_profit_loss = cached_player_data['relative_profit_loss']
                        absolute_profit_loss = cached_player_data['absolute_profit_loss']

                        # 获取玩家的颜色配置
                        profit_color = self.plugin.player_settings_manager.get_color_for_change(xuid, float(absolute_profit_loss))

                        # 构建内容
                        content += f"账户余额: ${balance:.2f}\n"
                        content += f"持仓市值: ${total_market_value:.2f}\n"
                        if contract_count > 0:
                            content += f"合约占用: ${contract_margin:.2f} ({contract_count}笔)\n"
                        content += f"总财富: ${total_wealth:.2f}\n"

                        # 显示绝对盈亏
                        if absolute_profit_loss > 0:
                            content += f"绝对盈亏: {profit_color}+${absolute_profit_loss:.2f}§r\n"
                        elif absolute_profit_loss < 0:
                            content += f"绝对盈亏: {profit_color}${absolute_profit_loss:.2f}§r\n"
                        else:
                            content += f"绝对盈亏: §7${absolute_profit_loss:.2f}§r\n"
                        
                        # 显示相对盈亏
                        if relative_profit_loss > 0:
                            content += f"相对盈亏: {profit_color}+{relative_profit_loss:.2f}%%§r\n"
                        elif relative_profit_loss < 0:
                            content += f"相对盈亏: {profit_color}{relative_profit_loss:.2f}%%§r\n"
                        else:
                            content += f"相对盈亏: §7{relative_profit_loss:.2f}%%§r\n"
                        
                    content += f"\n§r提示: 选择下方功能按钮进行操作"
                    
                    # 在主线程显示UI
                    def show_panel(p):
                        # 创建主面板
                        main_panel = ActionForm(
                            title="股票交易系统",
                            content=content
                        )
                        
                        # 添加功能按钮
                        main_panel.add_button(
                            "我的持仓",
                            on_click=lambda sender: self.show_holdings_panel(sender)
                        )

                        main_panel.add_button(
                            "合约交易(做空/杠杆)",
                            on_click=lambda sender: self.show_contract_center(sender)
                        )

                        main_panel.add_button(
                            "我的收藏",
                            on_click=lambda sender: self.show_favorites_panel(sender)
                        )
                        
                        main_panel.add_button(
                            "搜索股票",
                            on_click=lambda sender: self.show_search_panel(sender)
                        )
                        
                        main_panel.add_button(
                            "历史订单",
                            on_click=lambda sender: self.show_orders_panel(sender)
                        )
                        
                        main_panel.add_button(
                            "账户管理",
                            on_click=lambda sender: self.show_account_panel(sender)
                        )
                        
                        main_panel.add_button(
                            "个人设置",
                            on_click=lambda sender: self.show_player_settings_panel(sender)
                        )
                        
                        main_panel.add_button(
                            "盈亏排行榜",
                            on_click=lambda sender: self.show_leaderboard_menu(sender)
                        )
                        
                        main_panel.add_button(
                            "教学指引",
                            on_click=lambda sender: self.show_help_panel(sender)
                        )
                        
                        p.send_form(main_panel)
                    
                    self._run_for_player(player, show_panel)
                    
                except Exception as e:
                    print(f"加载主面板数据错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载数据时发生错误"))
            
            thread = threading.Thread(target=load_data)
            thread.start()
            
        except Exception as e:
            print(f"显示主面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示主面板时发生错误")
    
    def _show_activate_account_panel(self, player):
        """显示激活账户面板"""
        activate_form = ModalForm(
            title="激活股票账户",
            controls=[
                Label(text="欢迎来到股票交易系统！\n\n请转入初始资金以激活您的股票账户。\n建议转入至少$1000以开始交易。"),
                TextInput(
                    label="转入金额",
                    placeholder="请输入要转入的金额...",
                    default_value="1000"
                )
            ],
            on_submit=lambda sender, json_str: self._handle_activate_account(sender, json_str),
            on_close=lambda sender: None
        )
        player.send_form(activate_form)
    
    def _handle_activate_account(self, player, json_str: str):
        """处理激活账户"""
        try:
            data = json.loads(json_str)
            amount_str = data[1]
            
            try:
                amount = float(amount_str)
                if amount <= 0:
                    raise ValueError()
            except:
                player.send_message("§c请输入有效的金额（大于0的数字）")
                return
            
            # 检查玩家余额
            player_balance = self.plugin.economy_plugin.get_player_money(player)
            if player_balance < amount:
                player.send_message(f"§c您的游戏币余额不足，当前余额: ${player_balance:.2f}")
                return
            
            # 执行转账
            self.plugin.economy_plugin.decrease_player_money(player, amount)
            self.plugin.stock_dao.increase_balance(player.xuid, amount, is_transfer_in=True)
            
            player.send_message(f"§a成功激活股票账户并转入 ${amount:.2f}")
            
            # 显示主面板
            self.show_main_panel(player)
            
        except Exception as e:
            print(f"激活账户错误: {str(e)}")
            player.send_message("§c激活账户时发生错误")
    
    # ==================== 持仓面板 ====================
    def show_holdings_panel(self, player):
        """显示持仓面板"""
        try:
            xuid = player.xuid
            
            # 使用线程加载数据
            import threading
            
            def load_data():
                try:
                    holdings = self.plugin.stock_dao.get_shares(xuid, page=0, page_size=100)
                    
                    # 过滤掉股数为0的持仓
                    holdings = [h for h in holdings if h['share'] > 0]
                    
                    if not holdings:
                        def show_no_holdings(p):
                            no_holdings_form = ActionForm(
                                title="我的持仓",
                                content="您目前没有任何持仓\n\n提示: 使用搜索功能查找并购买股票",
                                on_close=lambda sender: self.show_main_panel(sender)
                            )
                            p.send_form(no_holdings_form)
                        
                        self._run_for_player(player, show_no_holdings)
                        return
                    
                    # 构建持仓按钮数据
                    buttons_data = []
                    
                    for holding in holdings:
                        stock_name = holding['stock_name']
                        share = holding['share']
                        
                        # 获取当前价格
                        current_price, _ = self.plugin.get_stock_last_price(stock_name)
                        
                        if current_price:
                            market_value = float(current_price) * share
                            
                            # 获取平均成本
                            avg_cost = self.plugin.stock_dao.get_average_cost(xuid, stock_name)
                            
                            if avg_cost:
                                cost = float(avg_cost) * share
                                profit_loss = market_value - cost
                                profit_loss_percent = (profit_loss / cost) * 100 if cost > 0 else 0
                                
                                # 获取颜色
                                profit_color = self.plugin.player_settings_manager.get_color_for_change(xuid, profit_loss)
                                
                                if profit_loss > 0:
                                    profit_text = f"{profit_color}+${profit_loss:.2f} (+{profit_loss_percent:.2f}%%)§r"
                                elif profit_loss < 0:
                                    profit_text = f"{profit_color}${profit_loss:.2f} ({profit_loss_percent:.2f}%%)§r"
                                else:
                                    profit_text = f"§7${profit_loss:.2f} (0.00%%)§r"
                            else:
                                profit_text = "无法计算"
                            
                            button_text = f"{stock_name}\n持股: {share} | 市值: ${market_value:.2f}\n{profit_text}"
                        else:
                            button_text = f"{stock_name}\n持股: {share} | 价格获取失败"
                        
                        buttons_data.append((button_text, stock_name))
                    
                    # 在主线程显示UI
                    def show_panel(p):
                        # 创建持仓列表面板
                        holdings_panel = ActionForm(
                            title="我的持仓",
                            content="点击股票查看详情和进行交易"
                        )
                        
                        for button_text, stock_name in buttons_data:
                            holdings_panel.add_button(
                                button_text,
                                on_click=lambda sender, stock=stock_name: self.show_stock_detail_panel(sender, stock, from_holdings=True)
                            )
                        
                        # 添加返回按钮
                        holdings_panel.add_button(
                            "返回主菜单",
                            on_click=lambda sender: self.show_main_panel(sender)
                        )
                        
                        p.send_form(holdings_panel)
                    
                    self._run_for_player(player, show_panel)
                    
                except Exception as e:
                    print(f"加载持仓数据错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载持仓数据时发生错误"))
            
            thread = threading.Thread(target=load_data)
            thread.start()
            
        except Exception as e:
            print(f"显示持仓面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示持仓面板时发生错误")
    
    # ==================== 收藏面板 ====================
    def show_favorites_panel(self, player):
        """显示收藏面板"""
        try:
            xuid = player.xuid
            
            # 使用线程加载数据
            import threading
            
            def load_data():
                try:
                    favorites = self.plugin.favorites_manager.get_favorites(xuid, page=0, page_size=20)
                    
                    if not favorites:
                        def show_no_favorites(p):
                            no_favorites_form = ActionForm(
                                title="我的收藏",
                                content="您还没有收藏任何股票\n\n提示: 使用搜索功能查找股票并添加收藏",
                                on_close=lambda sender: self.show_main_panel(sender)
                            )
                            p.send_form(no_favorites_form)
                        
                        self._run_for_player(player, show_no_favorites)
                        return
                    
                    # 构建收藏按钮数据
                    buttons_data = []
                    
                    for favorite in favorites:
                        stock_name = favorite['stock_name']
                        stock_display_name = favorite.get('stock_display_name', stock_name)
                        
                        # 获取当前价格
                        current_price, tradeable = self.plugin.get_stock_last_price(stock_name)
                        
                        if current_price:
                            status = "开盘" if tradeable else "盘后"
                            button_text = f"{stock_display_name}\n代码: {stock_name} | 价格: ${current_price:.2f} | {status}"
                        else:
                            button_text = f"{stock_display_name}\n代码: {stock_name} | 价格获取失败"
                        
                        buttons_data.append((button_text, stock_name))
                    
                    # 在主线程显示UI
                    def show_panel(p):
                        # 创建收藏列表面板
                        favorites_panel = ActionForm(
                            title="我的收藏",
                            content="点击股票查看详情和进行交互"
                        )
                        
                        for button_text, stock_name in buttons_data:
                            favorites_panel.add_button(
                                button_text,
                                on_click=lambda sender, stock=stock_name: self.show_stock_detail_panel(sender, stock)
                            )
                        
                        # 添加返回按钮
                        favorites_panel.add_button(
                            "返回主菜单",
                            on_click=lambda sender: self.show_main_panel(sender)
                        )
                        
                        p.send_form(favorites_panel)
                    
                    self._run_for_player(player, show_panel)
                    
                except Exception as e:
                    print(f"加载收藏数据错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载收藏数据时发生错误"))
            
            thread = threading.Thread(target=load_data)
            thread.start()
            
        except Exception as e:
            print(f"显示收藏面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示收藏面板时发生错误")
    
    # ==================== 搜索面板 ====================
    def show_search_panel(self, player):
        """显示搜索面板"""
        search_form = ModalForm(
            title="搜索股票",
            controls=[
                Label(text="请输入股票代码进行搜索\n\n例如: AAPL (苹果), TSLA (特斯拉), MSFT (微软)\nBTC-USD (比特币)"),
                TextInput(
                    label="股票代码",
                    placeholder="请输入股票代码...",
                    default_value=""
                )
            ],
            on_submit=lambda sender, json_str: self._handle_search_stock(sender, json_str),
            on_close=lambda sender: self.show_main_panel(sender)
        )
        player.send_form(search_form)
    
    def _handle_search_stock(self, player, json_str: str):
        """处理股票搜索"""
        try:
            data = json.loads(json_str)
            stock_name = data[1].strip().upper()
            
            if not stock_name:
                player.send_message("§c请输入有效的股票代码")
                return
            
            # 使用线程验证股票
            import threading
            
            def search_stock():
                try:
                    # 验证股票是否存在
                    price, tradeable = self.plugin.get_stock_last_price(stock_name)
                    
                    if price is None and tradeable is None:
                        def show_error(p):
                            error_form = ActionForm(
                                title="搜索失败",
                                content=f"未找到股票: {stock_name}\n\n可能原因:\n1. 股票代码输入错误\n2. 该股票市场暂不支持\n3. 网络连接问题",
                                on_close=lambda sender: self.show_search_panel(sender)
                            )
                            p.send_form(error_form)
                        
                        self._run_for_player(player, show_error)
                        return
                    
                    # 显示股票详情
                    self._run_for_player(player, lambda p: self.show_stock_detail_panel(p, stock_name))
                    
                except Exception as e:
                    print(f"搜索股票线程错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c搜索股票时发生错误"))
            
            thread = threading.Thread(target=search_stock)
            thread.start()
            
        except Exception as e:
            print(f"搜索股票错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c搜索股票时发生错误")
    
    # ==================== 股票详情面板 ====================
    def show_stock_detail_panel(self, player, stock_name: str, from_holdings: bool = False):
        """显示股票详情面板"""
        try:
            xuid = player.xuid
            
            # 使用线程加载数据
            import threading
            
            def load_data():
                try:
                    # 获取股票信息
                    current_price, tradeable = self.plugin.get_stock_last_price(stock_name)
                    
                    if current_price is None:
                        self._run_for_player(player, lambda p: p.send_message(f"§c无法获取股票 {stock_name} 的价格信息"))
                        return
                    
                    # 获取持仓信息
                    holding = self.plugin.stock_dao.get_player_stock_holding(xuid, stock_name)
                    
                    # 构建详情内容
                    content = f"=== {stock_name} ===\n\n"
                    content += f"当前价格: ${current_price:.2f}\n"
                    content += f"市场状态: {'开盘交易中' if tradeable else '盘后'}\n\n"
                    
                    if holding > 0:
                        market_value = float(current_price) * holding
                        avg_cost = self.plugin.stock_dao.get_average_cost(xuid, stock_name)
                        
                        content += f"持有股数: {holding}\n"
                        content += f"持仓市值: ${market_value:.2f}\n"
                        
                        if avg_cost:
                            cost = float(avg_cost) * holding
                            profit_loss = market_value - cost
                            profit_loss_percent = (profit_loss / cost) * 100 if cost > 0 else 0
                            
                            # 获取颜色
                            profit_color = self.plugin.player_settings_manager.get_color_for_change(xuid, profit_loss)
                            
                            content += f"平均成本: ${avg_cost:.2f}\n"
                            
                            if profit_loss > 0:
                                content += f"盈亏: {profit_color}+${profit_loss:.2f} (+{profit_loss_percent:.2f}%%)§r\n"
                            elif profit_loss < 0:
                                content += f"盈亏: {profit_color}${profit_loss:.2f} ({profit_loss_percent:.2f}%%)§r\n"
                            else:
                                content += f"盈亏: §7${profit_loss:.2f} (0.00%%)§r\n"
                    else:
                        content += f"您目前未持有该股票\n"
                    
                    # 检查是否已收藏
                    is_favorite = self.plugin.favorites_manager.is_favorite(xuid, stock_name)
                    
                    # 在主线程显示UI
                    def show_panel(p):
                        # 创建详情面板
                        detail_panel = ActionForm(
                            title=f"{stock_name}",
                            content=content
                        )
                        
                        # 添加买入按钮
                        detail_panel.add_button(
                            "买入",
                            on_click=lambda sender: self.show_buy_panel(sender, stock_name, current_price)
                        )

                        # 合约开仓按钮（做多/做空）
                        detail_panel.add_button(
                            "杠杆做多",
                            on_click=lambda sender: self.show_contract_open_panel(sender, stock_name, direction_index=0)
                        )

                        detail_panel.add_button(
                            "做空",
                            on_click=lambda sender: self.show_contract_open_panel(sender, stock_name, direction_index=1)
                        )

                        # 如果有持仓，添加卖出按钮
                        if holding > 0:
                            detail_panel.add_button(
                                "卖出",
                                on_click=lambda sender: self.show_sell_panel(sender, stock_name, current_price)
                            )
                        
                        # 添加收藏/取消收藏按钮
                        if is_favorite:
                            detail_panel.add_button(
                                "取消收藏",
                                on_click=lambda sender: self._handle_remove_favorite(sender, stock_name)
                            )
                        else:
                            detail_panel.add_button(
                                "添加收藏",
                                on_click=lambda sender: self._handle_add_favorite(sender, stock_name)
                            )
                        
                        # 添加查看历史价格按钮
                        detail_panel.add_button(
                            "查看价格走势",
                            on_click=lambda sender: self._show_price_history_panel(sender, stock_name)
                        )
                        
                        # 添加返回按钮
                        if from_holdings:
                            detail_panel.add_button(
                                "返回持仓",
                                on_click=lambda sender: self.show_holdings_panel(sender)
                            )
                        else:
                            detail_panel.add_button(
                                "返回主菜单",
                                on_click=lambda sender: self.show_main_panel(sender)
                            )
                        
                        p.send_form(detail_panel)
                    
                    self._run_for_player(player, show_panel)
                    
                except Exception as e:
                    print(f"加载股票详情数据错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载股票详情时发生错误"))
            
            thread = threading.Thread(target=load_data)
            thread.start()
            
        except Exception as e:
            print(f"显示股票详情错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示股票详情时发生错误")
    
    def _handle_add_favorite(self, player, stock_name: str):
        """处理添加收藏"""
        xuid = player.xuid
        
        if self.plugin.favorites_manager.add_favorite(xuid, stock_name):
            player.send_message(f"已添加 {stock_name} 到收藏")
        else:
            player.send_message(f"添加收藏失败（可能已存在）")
        
        # 返回股票详情
        self.show_stock_detail_panel(player, stock_name)
    
    def _handle_remove_favorite(self, player, stock_name: str):
        """处理取消收藏"""
        xuid = player.xuid
        
        if self.plugin.favorites_manager.remove_favorite(xuid, stock_name):
            player.send_message(f"已取消收藏 {stock_name}")
        else:
            player.send_message(f"取消收藏失败")
        
        # 返回股票详情
        self.show_stock_detail_panel(player, stock_name)
    
    def _show_price_history_panel(self, player, stock_name: str, unit="day"):
        """显示价格走势面板"""
        player.send_message(f"正在查询 {stock_name} 的价格走势...")
        
        # 使用线程执行查询，然后用调度器在主线程显示UI
        import threading
        
        def show_history(unit):
            try:
                xuid = player.xuid
                if unit == "minute":
                    price_list, tradeable = self.plugin.get_stock_last_price(stock_name, return_period=True)
                    unit_zh = "10分钟"
                elif unit == "day":
                    price_list, tradeable = self.plugin.get_stock_last_price(stock_name, period="1mo", interval="1d", return_period=True)
                    unit_zh = "10天"
                elif unit == "month":
                    price_list, tradeable = self.plugin.get_stock_last_price(stock_name, period="1y",interval="1mo", return_period=True)
                    unit_zh = "10个月"
                
                if price_list is None:
                    # 使用调度器在主线程发送消息
                    self._run_for_player(player, lambda p: p.send_message(f"无法获取 {stock_name} 的价格数据"))
                    return
                
                # 构建价格走势内容
                content = f"=== {stock_name} 价格走势 ===\n\n"
                content += f"近{unit_zh}价格变化:\n\n"
                
                price_list = price_list[-11:]  # 取最后11天（包括基准日）
                
                for idx in range(1, len(price_list)):
                    prev_price = price_list[idx - 1]
                    curr_price = price_list[idx]
                    change = curr_price - prev_price
                    change_percent = (change / prev_price * 100) if prev_price > 0 else 0
                    
                    # 获取颜色
                    color = self.plugin.player_settings_manager.get_color_for_change(xuid, change)
                    
                    # 格式化显示
                    if change > 0:
                        content += f"${curr_price:.2f} {color}▲+${abs(change):.2f} (+{change_percent:.2f}%)§r\n"
                    elif change < 0:
                        content += f"${curr_price:.2f} {color}▼${abs(change):.2f} ({change_percent:.2f}%)§r\n"
                    else:
                        content += f"${curr_price:.2f} §7━ ${abs(change):.2f} (0.00%%)§r\n"

                if len(price_list) == 0:
                    content += "暂无数据，请尝试切换时间范围\n"
                
                content += f"\n§7提示: 建议使用专业股票软件查询最新价格§r"
                
                # 使用调度器在主线程显示面板
                def show_panel(p):
                    history_panel = ActionForm(
                        title=f"{stock_name} 价格走势",
                        content=content
                    )

                    if unit == "minute":
                        next_unit = "day"
                        next_unit_zh = "10天"
                    elif unit == "day":
                        next_unit = "month"
                        next_unit_zh = "10个月"
                    elif unit == "month":
                        next_unit = "minute"
                        next_unit_zh = "10分钟"
                    else:
                        raise Exception(f"Unknown unit: {unit}")

                    history_panel.add_button(
                        f"切换近{next_unit_zh}交易价格",
                        on_click=lambda sender: self._show_price_history_panel(sender, stock_name, unit=next_unit)
                    )
                    
                    history_panel.add_button(
                        "返回股票详情",
                        on_click=lambda sender: self.show_stock_detail_panel(sender, stock_name)
                    )
                    
                    p.send_form(history_panel)
                
                self._run_for_player(player, show_panel)
                
            except Exception as e:
                print(f"查询价格走势错误: {str(e)}")
                import traceback
                traceback.print_exc()
                # 使用调度器在主线程发送消息
                self._run_for_player(player, lambda p: p.send_message("查询价格走势时发生错误"))
        
        thread = threading.Thread(target=show_history, args=[unit])
        thread.start()
    
    # ==================== 买入面板 ====================
    def show_buy_panel(self, player, stock_name: str, market_price:float):
        """显示买入面板"""
        try:
            xuid = player.xuid
            
            # 获取账户余额（这个不需要实时价格）
            balance = self.plugin.stock_dao.get_balance(xuid)
            fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
            fee = Decimal(str(market_price)) * Decimal(0.01) * Decimal(str(fee_rate))
            
            # 直接显示UI，不获取价格
            buy_form = ModalForm(
                title=f"买入 {stock_name}",
                controls=[
                    Label(text=f"账户余额: ${balance:.2f}\n单股市场价: ${market_price}\n手续费: {fee_rate}% ({fee})\n\n注意：市价单将以确认时的实时价格成交\n请输入购买信息:"),
                    TextInput(
                        label="购买股数",
                        placeholder="请输入要购买的股数（整数）...",
                        default_value="1"
                    ),
                    Dropdown(
                        label="订单类型",
                        options=["市价单（实时价格成交）", "限价单（指定价格）"],
                        default_index=0
                    ),
                    TextInput(
                        label="限价（仅限价单需要）",
                        placeholder="限价单时填写期望价格...",
                        default_value=""
                    )
                ],
                on_submit=lambda sender, json_str: self._confirm_buy_stock(sender, stock_name, json_str, market_price),
                on_close=lambda sender: self.show_stock_detail_panel(sender, stock_name)
            )
            
            player.send_form(buy_form)
            
        except Exception as e:
            print(f"显示买入面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示买入面板时发生错误")


    def _confirm_buy_stock(self, player, stock_name: str, json_str: str, market_price: float):
        try:            
            fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
            fee = Decimal(str(market_price)) * Decimal('0.01') * Decimal(str(fee_rate))

            data = json.loads(json_str)
            
            # 解析输入
            share_str = data[1]
            order_type_index = data[2]
            limit_price_str = data[3]

            if order_type_index == 0:  # 市价单
                price = market_price
                total = Decimal(str(price)) * Decimal(str(share_str))
                total += total * Decimal(str(fee_rate)) * Decimal('0.01')
                msg = f"单股市场价: ${market_price}\n手续费: {fee_rate}% ({fee})\n\n股数:{share_str}\n\n预计总价{total}\n\n 注意：市价单将以确认时的实时价格成交:"
            else:
                price = limit_price_str
                total = Decimal(str(price)) * Decimal(str(share_str))
                total += total * Decimal(str(fee_rate)) * Decimal('0.01')
                msg = f"单股市场价: ${market_price}\n订单限价:{price}\n 手续费: {fee_rate}% ({fee})\n\n股数:{share_str}\n\n预计总价{total}\n\n 注意：市价单将以确认时的实时价格成交:"
            
            # 直接显示UI，不获取价格
            buy_form = ActionForm(
                title=f"买入 {stock_name}",
                content=msg
            )

            buy_form.add_button(
                "确认买入",
                on_click=lambda sender: self._handle_buy_stock(sender, stock_name, json_str, market_price)
            )
            
            player.send_form(buy_form)
            
        except Exception as e:
            print(f"显示买入面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示买入面板时发生错误")

    def _confirm_sell_stock(self, player, stock_name: str, json_str: str, market_price: float, holding):
        try:            
            fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
            fee = Decimal(str(market_price)) * Decimal('0.01') * Decimal(str(fee_rate))

            data = json.loads(json_str)
            
            # 解析输入
            share_str = data[1]
            order_type_index = data[2]
            limit_price_str = data[3]

            if order_type_index == 0:  # 市价单
                price = market_price
                total = Decimal(str(price)) * Decimal(str(share_str))
                total -= total * Decimal(str(fee_rate)) * Decimal('0.01')  # 卖出时手续费从总收入中扣除
                msg = f"单股市场价: ${market_price}\n手续费: {fee_rate}% ({fee})\n\n股数:{share_str}\n\n预计总收入{total}\n\n 注意：市价单将以确认时的实时价格成交:"
            else:
                price = limit_price_str
                total = Decimal(str(price)) * Decimal(str(share_str))
                total -= total * Decimal(str(fee_rate)) * Decimal('0.01') # 卖出时手续费从总收入中扣除
                msg = f"单股市场价: ${market_price}\n订单限价:{price}\n 手续费: {fee_rate}% ({fee})\n\n股数:{share_str}\n\n预计总收入{total}\n\n 注意：市价单将以确认时的实时价格成交:"
            
            # 直接显示UI，不获取价格
            sell_form = ActionForm(
                title=f"卖出 {stock_name}",
                content=msg
            )

            sell_form.add_button(
                "确认卖出",
                on_click=lambda sender: self._handle_sell_stock(sender, stock_name, holding, json_str, market_price)
            )
            
            sell_form.add_button(
                "返回",
                on_click=lambda sender: self.show_sell_panel(sender, stock_name, market_price)
            )
            
            player.send_form(sell_form)
            
        except Exception as e:
            print(f"显示卖出确认面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示卖出确认面板时发生错误")


    def _handle_buy_stock(self, player, stock_name: str, json_str: str, market_price: float):
        """处理买入股票"""
        try:
            xuid = player.xuid
            data = json.loads(json_str)
            
            # 解析输入
            share_str = data[1]
            order_type_index = data[2]
            limit_price_str = data[3]
            
            # 验证股数
            try:
                share = int(share_str)
                if share <= 0:
                    raise ValueError()
            except:
                player.send_message("§c请输入有效的股数（大于0的整数）")
                self.show_buy_panel(player, stock_name, market_price)
                return
            
            # 构建参数
            params = ["buy", stock_name, share]
            if order_type_index != 0:  # 限价单
                try:
                    price = Decimal(limit_price_str)
                    if price <= 0:
                        raise ValueError()
                    params.append(price)
                except:
                    player.send_message("§c请输入有效的限价（大于0的数字）")
                    self.show_buy_panel(player, stock_name, market_price)
                    return
            
            callback_args = {
                "stock_name": stock_name
            }
            self.plugin.execute_command(player, params, True, self._handle_buy_stock_callback, callback_args)
            
        except Exception as e:
            print(f"买入股票错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c买入股票时发生错误")


    def _handle_buy_stock_callback(self, rtn, player, args):
        success, message = rtn
        stock_name = args["stock_name"]

        # 显示结果
        result_form = ActionForm(
            title="买入成功" if success else "买入失败",
            content=message,
            on_close=lambda sender: self.show_stock_detail_panel(sender, stock_name)
        )
        player.send_form(result_form)
        
    
    # ==================== 卖出面板 ====================
    def show_sell_panel(self, player, stock_name: str, market_price: float):
        """显示卖出面板"""
        try:
            xuid = player.xuid
            
            # 获取持仓（这个不需要实时价格）
            holding = self.plugin.stock_dao.get_player_stock_holding(xuid, stock_name)
            fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
            fee = Decimal(str(market_price)) * Decimal(0.01) * Decimal(str(fee_rate))
            
            if holding <= 0:
                player.send_message(f"§c您没有持有 {stock_name}")
                self.show_stock_detail_panel(player, stock_name)
                return
            
            # 直接显示UI，不获取价格
            sell_form = ModalForm(
                title=f"卖出 {stock_name}",
                controls=[
                    Label(text=f"持有股数: {holding}\n单股市场价: ${market_price}\n手续费: {fee_rate}% ({fee})%\n\n注意：市价单将以确认时的实时价格成交\n请输入卖出信息:"),
                    TextInput(
                        label="卖出股数",
                        placeholder=f"请输入要卖出的股数（最多{holding}）...",
                        default_value=str(holding)
                    ),
                    Dropdown(
                        label="订单类型",
                        options=["市价单（实时价格成交）", "限价单（指定价格）"],
                        default_index=0
                    ),
                    TextInput(
                        label="限价（仅限价单需要）",
                        placeholder="限价单时填写期望价格...",
                        default_value=""
                    )
                ],
                on_submit=lambda sender, json_str: self._confirm_sell_stock(sender, stock_name, json_str, market_price, holding),
                on_close=lambda sender: self.show_stock_detail_panel(sender, stock_name)
            )
            
            player.send_form(sell_form)
            
        except Exception as e:
            print(f"显示卖出面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示卖出面板时发生错误")
    
    def _handle_sell_stock(self, player, stock_name: str, max_holding: int, json_str: str, market_price: float):
        """处理卖出股票"""
        try:
            xuid = player.xuid
            data = json.loads(json_str)
            
            # 解析输入
            share_str = data[1]
            order_type_index = data[2]
            limit_price_str = data[3]
            
            # 验证股数
            try:
                share = int(share_str)
                if share <= 0 or share > max_holding:
                    raise ValueError()
            except:
                player.send_message(f"§c请输入有效的股数（1-{max_holding}）")
                self.show_sell_panel(player, stock_name, market_price)
                return
            
            # 构建参数
            params = ["sell", stock_name, share]
            if order_type_index != 0:  # 限价单
                try:
                    price = Decimal(limit_price_str)
                    if price <= 0:
                        raise ValueError()
                    params.append(price)
                except:
                    player.send_message("§c请输入有效的限价（大于0的数字）")
                    self.show_sell_panel(player, stock_name, market_price)
                    return
            
            callback_args = {
                "stock_name": stock_name
            }
            self.plugin.execute_command(player, params, True, self._handle_sell_stock_callback, callback_args)
            
        except Exception as e:
            print(f"卖出股票错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c卖出股票时发生错误")
    
    def _handle_sell_stock_callback(self, rtn, player, args):
        success, message = rtn
        stock_name = args["stock_name"]

        # 显示结果
        result_form = ActionForm(
            title="卖出成功" if success else "卖出失败",
            content=message,
            on_close=lambda sender: self.show_stock_detail_panel(sender, stock_name)
        )
        player.send_form(result_form)

    # ==================== 合约交易（做空/杠杆，逐仓） ====================
    def _contract_rate_color(self, rate_percent, warning_rate):
        """剩余保证金率着色：低于预警线红色，低于50%黄色，否则绿色"""
        if rate_percent <= warning_rate:
            return "§c"
        if rate_percent <= 50:
            return "§e"
        return "§a"

    def show_contract_center(self, player):
        """合约交易中心"""
        try:
            xuid = player.xuid
            import threading

            def load_data():
                try:
                    interest_hourly = self.plugin.setting_manager.get_contract_interest_hourly()
                    positions = self.plugin.stock_dao.get_open_margin_positions(xuid)

                    balance = self.plugin.stock_dao.get_balance(xuid)
                    summary = f"账户余额: ${balance:.2f}\n未平仓: {len(positions)} 笔"

                    locked = Decimal(0)
                    unrealized = Decimal(0)
                    priced = True
                    price_cache = {}
                    for pos in positions:
                        locked += Decimal(str(pos["margin"]))
                        stock = pos["stock_name"]
                        if stock not in price_cache:
                            try:
                                price_cache[stock] = self.plugin.get_stock_last_price(stock)[0]
                            except Exception:
                                price_cache[stock] = None
                        price = price_cache[stock]
                        if not price:
                            priced = False
                            continue
                        pnl, interest = self.plugin._calc_contract_pnl_interest(pos, price, interest_hourly)
                        unrealized += pnl - interest

                    if positions:
                        summary += f"\n占用保证金: ${float(locked):.2f}"
                        if priced:
                            profit_color = self.plugin.player_settings_manager.get_color_for_change(xuid, float(unrealized))
                            summary += f"\n合约浮动盈亏: {profit_color}{float(unrealized):+.2f}§r (已扣应计利息)"
                    else:
                        fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
                        summary += f"\n\n§7逐仓模式：爆仓最多亏掉该笔保证金\n§7手续费 {fee_rate}%/开平仓，利息 {interest_hourly}%/小时(借入部分)"

                    def show_panel(p):
                        panel = ActionForm(
                            title="合约交易",
                            content=f"=== 合约交易中心（逐仓） ===\n\n{summary}\n\n§c警示: 杠杆放大收益也放大亏损，强平以系统实时检测为准"
                        )
                        panel.add_button(
                            "我的仓位",
                            on_click=lambda sender: self.show_contract_positions_panel(sender)
                        )
                        panel.add_button(
                            "开仓（做多/做空）",
                            on_click=lambda sender: self.show_contract_open_panel(sender)
                        )
                        panel.add_button(
                            "仓位历史",
                            on_click=lambda sender: self.show_contract_history_panel(sender)
                        )
                        panel.add_button(
                            "合约教学",
                            on_click=lambda sender: self.show_contract_teaching_panel(sender)
                        )
                        panel.add_button(
                            "返回主菜单",
                            on_click=lambda sender: self.show_main_panel(sender)
                        )
                        p.send_form(panel)

                    self._run_for_player(player, show_panel)

                except Exception as e:
                    print(f"加载合约中心数据错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载合约中心时发生错误"))

            threading.Thread(target=load_data).start()

        except Exception as e:
            print(f"显示合约中心错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示合约中心时发生错误")

    def show_contract_open_panel(self, player, stock_name: str = None, direction_index: int = 0):
        """合约开仓表单"""
        try:
            xuid = player.xuid
            balance = self.plugin.stock_dao.get_balance(xuid)
            leverage_options = self.plugin.setting_manager.get_contract_leverage_options()
            min_margin = self.plugin.setting_manager.get_contract_min_margin()
            fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
            interest_hourly = self.plugin.setting_manager.get_contract_interest_hourly()

            open_form = ModalForm(
                title="合约开仓",
                controls=[
                    Label(
                        text=f"§c逐仓合约：爆仓最多亏掉该笔保证金\n\n"
                             f"账户余额: ${balance:.2f}\n"
                             f"手续费: {fee_rate}% (开仓/平仓各收一次)\n"
                             f"资金利息: {interest_hourly}%/小时 (按借入部分计)\n"
                             f"最低保证金: ${min_margin:.0f}\n\n"
                             f"§e做多=看涨赚钱，做空=看跌赚钱。杠杆越高，强平越快。"),
                    TextInput(
                        label="股票代码",
                        placeholder="例如 AAPL / TSLA / BTC-USD ...",
                        default_value=stock_name or ""
                    ),
                    Dropdown(
                        label="方向",
                        options=["▲ 做多（看涨）", "▼ 做空（看跌）"],
                        default_index=1 if direction_index == 1 else 0
                    ),
                    TextInput(
                        label="保证金（元）",
                        placeholder=f"最低 {min_margin:.0f} ...",
                        default_value=str(int(min_margin))
                    ),
                    Dropdown(
                        label="杠杆倍数",
                        options=[f"{l}x" for l in leverage_options],
                        default_index=0
                    )
                ],
                on_submit=lambda sender, json_str: self._handle_contract_open_submit(sender, json_str),
                on_close=lambda sender: self.show_contract_center(sender)
            )
            player.send_form(open_form)

        except Exception as e:
            print(f"显示合约开仓面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示合约开仓面板时发生错误")

    def _handle_contract_open_submit(self, player, json_str: str):
        """解析开仓输入，拉现价后弹出确认面板"""
        try:
            data = json.loads(json_str)
            stock_input = str(data[1] or "").strip().upper()
            direction_index = data[2]
            margin_str = str(data[3] or "").strip()
            leverage_index = data[4]

            if not stock_input:
                player.send_message("§c请输入股票代码")
                self.show_contract_open_panel(player, direction_index=direction_index)
                return

            try:
                margin_amount = Decimal(margin_str)
                if margin_amount <= 0:
                    raise ValueError()
            except Exception:
                player.send_message("§c请输入有效的保证金金额")
                self.show_contract_open_panel(player, stock_input, direction_index)
                return

            leverage_options = self.plugin.setting_manager.get_contract_leverage_options()
            leverage = leverage_options[leverage_index] if leverage_index < len(leverage_options) else leverage_options[0]
            direction = "short" if direction_index == 1 else "long"

            import threading

            def load_price():
                try:
                    market_price, tradeable = self.plugin.get_stock_last_price(stock_input)
                    if tradeable is None or market_price is None:
                        self._run_for_player(player, lambda p: p.send_message(
                            f"§c无法获取 {stock_input} 的价格（代码错误或市场不支持）"))
                        return

                    price = Decimal(str(market_price))
                    share = int(margin_amount * Decimal(leverage) / price)
                    min_margin = Decimal(str(self.plugin.setting_manager.get_contract_min_margin()))

                    if share < 1 or margin_amount < min_margin:
                        need = price / Decimal(leverage)
                        self._run_for_player(player, lambda p: p.send_message(
                            f"§c保证金不足：{stock_input} 现价 ${float(price):.2f}，{leverage}x 杠杆至少需要 ${float(need):.2f} 保证金"))
                        return

                    open_value = price * Decimal(share)
                    fee_rate = Decimal(str(self.plugin.setting_manager.get_trading_fee_rate() / 100))
                    open_fee = open_value * fee_rate
                    total_cost = margin_amount + open_fee

                    pos_view = {
                        "direction": direction,
                        "entry_price": price,
                        "share": share,
                        "margin": margin_amount,
                        "open_time": time.time(),
                    }
                    liq_price = self.plugin._calc_contract_liquidation_price(
                        pos_view, self.plugin.setting_manager.get_contract_maintenance_rate()
                    )

                    direction_text = "▲ 做多" if direction == "long" else "▼ 做空"
                    content = (
                        f"=== 合约开仓确认 ===\n\n"
                        f"标的: {stock_input}   现价: ${float(price):.2f}\n"
                        f"方向: {direction_text}   杠杆: {leverage}x\n"
                        f"股数: {share} 股（按保证金可开上限）\n"
                        f"仓位价值: ${float(open_value):.2f}\n\n"
                        f"占用保证金: ${float(margin_amount):.2f}\n"
                        f"开仓手续费: ${float(open_fee):.2f}\n"
                        f"合计扣款: ${float(total_cost):.2f}\n\n"
                        f"§c预估强平价: ${float(liq_price):.2f}\n"
                        f"§7权益随持仓时间被利息消耗，实际强平价会略有偏移；\n"
                        f"§7强平以系统实时检测为准，存在至多数十秒延迟。"
                    )

                    def show_confirm(p):
                        confirm_form = ActionForm(title="合约开仓确认", content=content)
                        confirm_form.add_button(
                            "确认开仓",
                            on_click=lambda sender: self._handle_contract_open_confirm(
                                sender, stock_input, direction, margin_amount, leverage
                            )
                        )
                        confirm_form.add_button(
                            "返回修改",
                            on_click=lambda sender: self.show_contract_open_panel(
                                sender, stock_input, direction_index
                            )
                        )
                        p.send_form(confirm_form)

                    self._run_for_player(player, show_confirm)

                except Exception as e:
                    print(f"合约开仓预览错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c合约开仓预览时发生错误"))

            threading.Thread(target=load_price).start()

        except Exception as e:
            print(f"处理合约开仓输入错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c处理合约开仓输入时发生错误")

    def _handle_contract_open_confirm(self, player, stock_name, direction, margin_amount, leverage):
        xuid = player.xuid
        callback_args = {"stock_name": stock_name}
        params = [
            "long" if direction == "long" else "short",
            stock_name, str(margin_amount), str(leverage)
        ]
        self.plugin.execute_command(player, params, True, self._handle_contract_open_callback, callback_args)

    def _handle_contract_open_callback(self, rtn, player, args):
        success, message = rtn
        stock_name = args["stock_name"]
        result_form = ActionForm(
            title="开仓成功" if success else "开仓失败",
            content=message,
            on_close=lambda sender: self.show_contract_center(sender)
        )
        result_form.add_button(
            "查看我的仓位",
            on_click=lambda sender: self.show_contract_positions_panel(sender)
        )
        result_form.add_button(
            "返回合约中心",
            on_click=lambda sender: self.show_contract_center(sender)
        )
        player.send_form(result_form)

    def show_contract_positions_panel(self, player, page: int = 0):
        """未平仓仓位列表（带风险色标）"""
        try:
            xuid = player.xuid
            import threading

            def load_data():
                try:
                    positions = self.plugin.stock_dao.get_margin_positions(
                        xuid, status='open', page=page, page_size=8
                    )
                    if not positions:
                        def show_empty(p):
                            empty_form = ActionForm(
                                title="我的仓位",
                                content="当前没有未平仓合约\n\n提示: 在股票详情页或合约中心开仓",
                                on_close=lambda sender: self.show_contract_center(sender)
                            )
                            empty_form.add_button(
                                "开仓",
                                on_click=lambda sender: self.show_contract_open_panel(sender)
                            )
                            empty_form.add_button(
                                "返回合约中心",
                                on_click=lambda sender: self.show_contract_center(sender)
                            )
                            p.send_form(empty_form)

                        self._run_for_player(player, show_empty)
                        return

                    interest_hourly = self.plugin.setting_manager.get_contract_interest_hourly()
                    maintenance_rate = self.plugin.setting_manager.get_contract_maintenance_rate()
                    warning_rate = self.plugin.setting_manager.get_contract_warning_rate()

                    buttons_data = []
                    price_cache = {}
                    total_equity = Decimal(0)
                    for pos in positions:
                        stock = pos["stock_name"]
                        if stock not in price_cache:
                            try:
                                price_cache[stock] = self.plugin.get_stock_last_price(stock)[0]
                            except Exception:
                                price_cache[stock] = None
                        price = price_cache[stock]

                        direction_mark = "▲多" if pos["direction"] == "long" else "▼空"
                        if not price:
                            button_text = f"#{pos['id']} {stock} {direction_mark} {pos['leverage']}x\n{pos['share']}股 @ ${float(pos['entry_price']):.2f}\n§7价格获取失败"
                            buttons_data.append((button_text, pos["id"]))
                            continue

                        pnl, interest = self.plugin._calc_contract_pnl_interest(pos, price, interest_hourly)
                        margin = Decimal(str(pos["margin"]))
                        equity = margin + pnl - interest
                        total_equity += equity
                        rate = float(equity / margin * 100) if margin > 0 else 0.0
                        rate_color = self._contract_rate_color(rate, warning_rate)
                        profit_color = self.plugin.player_settings_manager.get_color_for_change(xuid, float(pnl))

                        button_text = (
                            f"#{pos['id']} {stock} {direction_mark} {pos['leverage']}x\n"
                            f"{pos['share']}股 @ ${float(pos['entry_price']):.2f} → ${float(price):.2f}\n"
                            f"盈亏 {profit_color}{float(pnl):+.2f}§r | 保证金率 {rate_color}{rate:.1f}%§r"
                        )
                        buttons_data.append((button_text, pos["id"]))

                    summary = ""
                    if page == 0:
                        summary = f"权益合计: ${float(total_equity):.2f}\n\n"

                    def show_panel(p):
                        panel = ActionForm(
                            title="我的仓位",
                            content=f"{summary}点击仓位查看详情/平仓"
                        )
                        for button_text, position_id in buttons_data:
                            panel.add_button(
                                button_text,
                                on_click=lambda sender, pid=position_id: self.show_contract_position_detail(sender, pid)
                            )
                        if len(positions) >= 8:
                            panel.add_button(
                                "下一页",
                                on_click=lambda sender: self.show_contract_positions_panel(sender, page + 1)
                            )
                        if page > 0:
                            panel.add_button(
                                "上一页",
                                on_click=lambda sender: self.show_contract_positions_panel(sender, page - 1)
                            )
                        panel.add_button(
                            "返回合约中心",
                            on_click=lambda sender: self.show_contract_center(sender)
                        )
                        p.send_form(panel)

                    self._run_for_player(player, show_panel)

                except Exception as e:
                    print(f"加载合约仓位错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载合约仓位时发生错误"))

            threading.Thread(target=load_data).start()

        except Exception as e:
            print(f"显示合约仓位面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示合约仓位面板时发生错误")

    def show_contract_position_detail(self, player, position_id: int):
        """仓位详情：风险指标 + 平仓操作"""
        try:
            xuid = player.xuid
            import threading

            def load_data():
                try:
                    pos = self.plugin.stock_dao.get_margin_position(position_id)
                    if pos is None or str(pos["player_xuid"]) != str(xuid):
                        self._run_for_player(player, lambda p: p.send_message(f"§c仓位 #{position_id} 不存在"))
                        return
                    if pos["status"] != "open":
                        self._run_for_player(player, lambda p: self.show_contract_history_panel(p))
                        return

                    market_price, _ = self.plugin.get_stock_last_price(pos["stock_name"])
                    if not market_price:
                        self._run_for_player(player, lambda p: p.send_message(
                            f"§c无法获取 {pos['stock_name']} 的当前价格"))
                        return

                    price = Decimal(str(market_price))
                    interest_hourly = self.plugin.setting_manager.get_contract_interest_hourly()
                    maintenance_rate = self.plugin.setting_manager.get_contract_maintenance_rate()
                    warning_rate = self.plugin.setting_manager.get_contract_warning_rate()

                    pnl, interest = self.plugin._calc_contract_pnl_interest(pos, price, interest_hourly)
                    margin = Decimal(str(pos["margin"]))
                    equity = margin + pnl - interest
                    rate = float(equity / margin * 100) if margin > 0 else 0.0
                    rate_color = self._contract_rate_color(rate, warning_rate)
                    profit_color = self.plugin.player_settings_manager.get_color_for_change(xuid, float(pnl))
                    liq_price = self.plugin._calc_contract_liquidation_price(pos, maintenance_rate)

                    direction_text = "▲ 做多" if pos["direction"] == "long" else "▼ 做空"
                    hold_hours = max(time.time() - float(pos["open_time"]), 0.0) / 3600.0

                    content = (
                        f"=== 仓位 #{pos['id']} ===\n\n"
                        f"标的: {pos['stock_name']}   {direction_text} {pos['leverage']}x\n"
                        f"股数: {pos['share']} 股   持仓: {hold_hours:.1f} 小时\n\n"
                        f"开仓价: ${float(pos['entry_price']):.2f}\n"
                        f"现价: ${float(price):.2f}\n"
                        f"浮动盈亏: {profit_color}{float(pnl):+.2f}§r\n"
                        f"应计利息: -${float(interest):.2f}\n"
                        f"占用保证金: ${float(margin):.2f}\n"
                        f"权益(返还估算): ${float(equity):.2f}\n"
                        f"剩余保证金率: {rate_color}{rate:.1f}%§r (强平线 {maintenance_rate:.0f}%)\n"
                        f"预估强平价: §c${float(liq_price):.2f}§r\n\n"
                        f"§7平仓另有手续费 {self.plugin.setting_manager.get_trading_fee_rate()}%"
                    )

                    def show_panel(p):
                        panel = ActionForm(title=f"仓位 #{pos['id']}", content=content)
                        panel.add_button(
                            "全部平仓",
                            on_click=lambda sender: self._confirm_contract_close(sender, pos["id"], None)
                        )
                        panel.add_button(
                            "部分平仓",
                            on_click=lambda sender: self._show_partial_close_panel(sender, pos["id"], pos["share"])
                        )
                        panel.add_button(
                            "追加保证金",
                            on_click=lambda sender: self._show_add_margin_panel(sender, pos["id"])
                        )
                        panel.add_button(
                            "刷新",
                            on_click=lambda sender: self.show_contract_position_detail(sender, pos["id"])
                        )
                        panel.add_button(
                            "返回仓位列表",
                            on_click=lambda sender: self.show_contract_positions_panel(sender)
                        )
                        p.send_form(panel)

                    self._run_for_player(player, show_panel)

                except Exception as e:
                    print(f"加载仓位详情错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载仓位详情时发生错误"))

            threading.Thread(target=load_data).start()

        except Exception as e:
            print(f"显示仓位详情错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示仓位详情时发生错误")

    def _show_partial_close_panel(self, player, position_id: int, max_share: int):
        """部分平仓输入面板"""
        partial_form = ModalForm(
            title=f"部分平仓 #{position_id}",
            controls=[
                Label(text=f"当前持仓 {max_share} 股\n输入要平掉的股数（1-{max_share}）"),
                TextInput(
                    label="平仓股数",
                    placeholder=f"1-{max_share} ...",
                    default_value="1"
                )
            ],
            on_submit=lambda sender, json_str: self._handle_partial_close_input(sender, position_id, max_share, json_str),
            on_close=lambda sender: self.show_contract_position_detail(sender, position_id)
        )
        player.send_form(partial_form)

    def _handle_partial_close_input(self, player, position_id: int, max_share: int, json_str: str):
        try:
            data = json.loads(json_str)
            share = int(str(data[1] or "").strip())
            if share < 1 or share > max_share:
                player.send_message(f"§c请输入 1-{max_share} 之间的股数")
                self._show_partial_close_panel(player, position_id, max_share)
                return
            self._confirm_contract_close(player, position_id, share)
        except Exception:
            player.send_message("§c请输入有效的股数")
            self._show_partial_close_panel(player, position_id, max_share)

    def _show_add_margin_panel(self, player, position_id: int):
        """追加保证金输入面板"""
        try:
            xuid = player.xuid
            pos = self.plugin.stock_dao.get_margin_position(position_id)
            if pos is None or str(pos["player_xuid"]) != str(xuid) or pos["status"] != "open":
                player.send_message("§c该仓位不存在或已平仓")
                self.show_contract_positions_panel(player)
                return

            balance = self.plugin.stock_dao.get_balance(xuid)
            add_form = ModalForm(
                title=f"追加保证金 #{position_id}",
                controls=[
                    Label(
                        text=f"仓位: {pos['stock_name']} "
                             f"{'▲多' if pos['direction'] == 'long' else '▼空'} {pos['leverage']}x\n"
                             f"当前保证金: ${float(pos['margin']):.2f}\n"
                             f"账户余额: ${balance:.2f}\n\n"
                             f"§e追加后强平价远离现价，借入减少、利息变慢；\n"
                             f"§c爆仓时追加部分同样会亏掉。"),
                    TextInput(
                        label="追加金额",
                        placeholder="输入要从余额划入的金额...",
                        default_value=""
                    )
                ],
                on_submit=lambda sender, json_str: self._handle_add_margin_input(sender, position_id, json_str),
                on_close=lambda sender: self.show_contract_position_detail(sender, position_id)
            )
            player.send_form(add_form)

        except Exception as e:
            print(f"显示追加保证金面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示追加保证金面板时发生错误")

    def _handle_add_margin_input(self, player, position_id: int, json_str: str):
        """校验金额并展示追加后风险指标预览"""
        try:
            data = json.loads(json_str)
            amount_str = str(data[1] or "").strip()
            try:
                amount = Decimal(amount_str)
                if amount <= 0:
                    raise ValueError()
            except Exception:
                player.send_message("§c请输入有效的追加金额（大于0）")
                self._show_add_margin_panel(player, position_id)
                return

            xuid = player.xuid
            import threading

            def load_preview():
                try:
                    pos = self.plugin.stock_dao.get_margin_position(position_id)
                    if pos is None or pos["status"] != "open":
                        self._run_for_player(player, lambda p: p.send_message("§c该仓位已平仓或不存在"))
                        return

                    balance = self.plugin.stock_dao.get_balance(xuid)
                    if balance is None or Decimal(str(balance)) < amount:
                        self._run_for_player(player, lambda p: p.send_message(
                            f"§c余额不足：需 {float(amount):.2f} 元，当前余额 {balance} 元"))
                        return

                    market_price, _ = self.plugin.get_stock_last_price(pos["stock_name"])
                    interest_hourly = self.plugin.setting_manager.get_contract_interest_hourly()
                    maintenance_rate = self.plugin.setting_manager.get_contract_maintenance_rate()
                    warning_rate = self.plugin.setting_manager.get_contract_warning_rate()

                    old_margin = Decimal(str(pos["margin"]))
                    new_margin = old_margin + amount
                    new_liq_text = old_liq_text = "获取失败"
                    old_rate_text = new_rate_text = "获取失败"
                    if market_price:
                        pnl, interest = self.plugin._calc_contract_pnl_interest(pos, market_price, interest_hourly)
                        old_equity = old_margin + pnl - interest
                        new_equity = new_margin + pnl - interest
                        if old_margin > 0:
                            old_rate_text = f"{float(old_equity / old_margin * 100):.1f}%"
                        if new_margin > 0:
                            new_rate_text = f"{float(new_equity / new_margin * 100):.1f}%"
                            new_rate_color = self._contract_rate_color(
                                float(new_equity / new_margin * 100), warning_rate
                            )
                            new_rate_text = f"{new_rate_color}{new_rate_text}§r"
                        old_liq_text = f"${float(self.plugin._calc_contract_liquidation_price(pos, maintenance_rate)):.2f}"
                        liq_view = {
                            "direction": pos["direction"],
                            "entry_price": pos["entry_price"],
                            "share": pos["share"],
                            "margin": float(new_margin),
                        }
                        new_liq_text = f"${float(self.plugin._calc_contract_liquidation_price(liq_view, maintenance_rate)):.2f}"

                    content = (
                        f"=== 追加保证金确认 ===\n\n"
                        f"仓位 #{pos['id']} {pos['stock_name']} "
                        f"{'▲多' if pos['direction'] == 'long' else '▼空'} {pos['leverage']}x\n"
                        f"追加金额: ${float(amount):.2f}\n"
                        f"保证金: ${float(old_margin):.2f} → ${float(new_margin):.2f}\n\n"
                        f"剩余保证金率: {old_rate_text} → {new_rate_text}\n"
                        f"预估强平价: {old_liq_text} → §a{new_liq_text}§r\n\n"
                        f"§7追加金额将从股票账户余额中扣除"
                    )

                    def show_confirm(p):
                        confirm_form = ActionForm(title="追加保证金确认", content=content)
                        confirm_form.add_button(
                            "确认追加",
                            on_click=lambda sender: self._handle_add_margin_confirm(
                                sender, position_id, amount
                            )
                        )
                        confirm_form.add_button(
                            "返回仓位详情",
                            on_click=lambda sender: self.show_contract_position_detail(sender, position_id)
                        )
                        p.send_form(confirm_form)

                    self._run_for_player(player, show_confirm)

                except Exception as e:
                    print(f"追加保证金预览错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c生成追加预览时发生错误"))

            threading.Thread(target=load_preview).start()

        except Exception as e:
            print(f"处理追加保证金输入错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c处理追加保证金输入时发生错误")

    def _handle_add_margin_confirm(self, player, position_id: int, amount):
        xuid = player.xuid
        params = ["margin", str(position_id), str(amount)]
        callback_args = {"position_id": position_id}
        self.plugin.execute_command(player, params, True, self._handle_add_margin_callback, callback_args)

    def _handle_add_margin_callback(self, rtn, player, args):
        success, message = rtn
        position_id = args["position_id"]
        result_form = ActionForm(
            title="追加成功" if success else "追加失败",
            content=message,
            on_close=lambda sender: self.show_contract_position_detail(sender, position_id)
        )
        result_form.add_button(
            "返回仓位详情",
            on_click=lambda sender: self.show_contract_position_detail(sender, position_id)
        )
        result_form.add_button(
            "返回仓位列表",
            on_click=lambda sender: self.show_contract_positions_panel(sender)
        )
        player.send_form(result_form)

    def _confirm_contract_close(self, player, position_id: int, share):
        """平仓确认面板（share=None 为全部平仓）"""
        try:
            import threading

            def load_data():
                try:
                    pos = self.plugin.stock_dao.get_margin_position(position_id)
                    if pos is None or pos["status"] != "open":
                        self._run_for_player(player, lambda p: p.send_message("§c该仓位已平仓或不存在"))
                        return

                    market_price, _ = self.plugin.get_stock_last_price(pos["stock_name"])
                    if not market_price:
                        self._run_for_player(player, lambda p: p.send_message("§c无法获取当前价格，请稍后再试"))
                        return

                    price = Decimal(str(market_price))
                    full_close = share is None or share >= pos["share"]
                    close_share = pos["share"] if full_close else share
                    interest_hourly = self.plugin.setting_manager.get_contract_interest_hourly()
                    pnl, interest = self.plugin._calc_contract_pnl_interest(pos, price, interest_hourly)

                    proportion = Decimal(close_share) / Decimal(pos["share"])
                    fee_rate = Decimal(str(self.plugin.setting_manager.get_trading_fee_rate() / 100))
                    close_fee = price * Decimal(close_share) * fee_rate
                    returned = (Decimal(str(pos["margin"])) + pnl) * proportion - close_fee - interest * proportion

                    action_text = "全部平仓" if full_close else f"平仓 {close_share}/{pos['share']} 股"
                    content = (
                        f"=== 平仓确认 ===\n\n"
                        f"仓位 #{pos['id']} {pos['stock_name']} "
                        f"{'▲多' if pos['direction'] == 'long' else '▼空'} {pos['leverage']}x\n"
                        f"操作: {action_text}\n"
                        f"现价: ${float(price):.2f}\n\n"
                        f"预计结算款: ${float(returned):.2f}\n"
                        f"(含平仓费 -${float(close_fee):.2f}，利息 -${float(interest * proportion):.2f})\n\n"
                        f"§7市价平仓以确认时的实时价格成交"
                    )

                    def show_confirm(p):
                        confirm_form = ActionForm(title="平仓确认", content=content)
                        confirm_form.add_button(
                            f"确认{action_text}",
                            on_click=lambda sender: self._handle_contract_close(
                                sender, position_id, None if full_close else close_share
                            )
                        )
                        confirm_form.add_button(
                            "返回仓位详情",
                            on_click=lambda sender: self.show_contract_position_detail(sender, position_id)
                        )
                        p.send_form(confirm_form)

                    self._run_for_player(player, show_confirm)

                except Exception as e:
                    print(f"平仓确认错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c生成平仓确认时发生错误"))

            threading.Thread(target=load_data).start()

        except Exception as e:
            print(f"显示平仓确认错误: {str(e)}")
            player.send_message("§c显示平仓确认时发生错误")

    def _handle_contract_close(self, player, position_id: int, share):
        xuid = player.xuid
        params = ["close", str(position_id)]
        if share is not None:
            params.append(str(share))
        callback_args = {"position_id": position_id}
        self.plugin.execute_command(player, params, True, self._handle_contract_close_callback, callback_args)

    def _handle_contract_close_callback(self, rtn, player, args):
        success, message = rtn
        position_id = args["position_id"]
        result_form = ActionForm(
            title="平仓成功" if success else "平仓失败",
            content=message,
            on_close=lambda sender: self.show_contract_positions_panel(sender)
        )
        result_form.add_button(
            "返回仓位列表",
            on_click=lambda sender: self.show_contract_positions_panel(sender)
        )
        player.send_form(result_form)

    def show_contract_history_panel(self, player, page: int = 0):
        """已平仓仓位历史"""
        try:
            xuid = player.xuid
            import threading

            def load_data():
                try:
                    rows = self.plugin.stock_dao.get_margin_positions(
                        xuid, exclude_open=True, page=page, page_size=8
                    )
                    closed_rows = list(rows)

                    if not closed_rows:
                        def show_empty(p):
                            empty_form = ActionForm(
                                title="仓位历史",
                                content="暂无已平仓记录",
                                on_close=lambda sender: self.show_contract_center(sender)
                            )
                            empty_form.add_button(
                                "返回合约中心",
                                on_click=lambda sender: self.show_contract_center(sender)
                            )
                            p.send_form(empty_form)

                        self._run_for_player(player, show_empty)
                        return

                    buttons_data = []
                    for pos in closed_rows:
                        direction_mark = "▲多" if pos["direction"] == "long" else "▼空"
                        if pos["status"] == "liquidated":
                            status_text = "§c爆仓"
                        else:
                            status_text = "平仓"
                        pnl = float(pos["realized_pnl"] or 0)
                        profit_color = self.plugin.player_settings_manager.get_color_for_change(xuid, pnl)
                        button_text = (
                            f"#{pos['id']} {pos['stock_name']} {direction_mark} {pos['leverage']}x [{status_text}§r]\n"
                            f"{pos['share']}股 @ ${float(pos['entry_price']):.2f} → ${float(pos['close_price'] or 0):.2f}\n"
                            f"净盈亏 {profit_color}{pnl:+.2f}§r"
                        )
                        buttons_data.append((button_text, pos["id"]))

                    def show_panel(p):
                        panel = ActionForm(title="仓位历史", content="点击查看该笔平仓结果")
                        for button_text, position_id in buttons_data:
                            panel.add_button(
                                button_text,
                                on_click=lambda sender, pid=position_id: self._show_closed_position_detail(sender, pid)
                            )
                        if len(rows) >= 8:
                            panel.add_button(
                                "下一页",
                                on_click=lambda sender: self.show_contract_history_panel(sender, page + 1)
                            )
                        if page > 0:
                            panel.add_button(
                                "上一页",
                                on_click=lambda sender: self.show_contract_history_panel(sender, page - 1)
                            )
                        panel.add_button(
                            "返回合约中心",
                            on_click=lambda sender: self.show_contract_center(sender)
                        )
                        p.send_form(panel)

                    self._run_for_player(player, show_panel)

                except Exception as e:
                    print(f"加载仓位历史错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载仓位历史时发生错误"))

            threading.Thread(target=load_data).start()

        except Exception as e:
            print(f"显示仓位历史错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示仓位历史时发生错误")

    def _show_closed_position_detail(self, player, position_id: int):
        """已平仓仓位结算单"""
        try:
            import threading

            def load_data():
                try:
                    pos = self.plugin.stock_dao.get_margin_position(position_id)
                    if pos is None or pos["status"] == "open":
                        self._run_for_player(player, lambda p: p.send_message("§c记录不存在"))
                        return

                    is_liquidated = pos["status"] == "liquidated"
                    direction_text = "▲ 做多" if pos["direction"] == "long" else "▼ 做空"
                    hold_hours = 0.0
                    if pos["close_time"] and pos["open_time"]:
                        hold_hours = max(float(pos["close_time"]) - float(pos["open_time"]), 0.0) / 3600.0

                    pnl = float(pos["realized_pnl"] or 0)
                    profit_color = self.plugin.player_settings_manager.get_color_for_change(
                        pos["player_xuid"], pnl
                    )

                    fee_text = f"${float(pos['close_fee'] or 0):.2f}"
                    if is_liquidated:
                        fee_text += f" + 强平费 ${float(pos['liquidation_fee'] or 0):.2f}"

                    liquidated_line = "§c※ 该仓位已被系统强制平仓（爆仓）§r\n" if is_liquidated else ""
                    content = (
                        f"=== 平仓结算单 #{pos['id']} ===\n\n"
                        f"标的: {pos['stock_name']} {direction_text} {pos['leverage']}x\n"
                        f"{liquidated_line}"
                        f"股数: {pos['share']} 股   持仓: {hold_hours:.1f} 小时\n\n"
                        f"开仓价: ${float(pos['entry_price']):.2f}\n"
                        f"平仓价: ${float(pos['close_price'] or 0):.2f}\n"
                        f"开仓费: ${float(pos['open_fee'] or 0):.2f}\n"
                        f"平仓费/强平费: {fee_text}\n"
                        f"利息: ${float(pos['interest'] or 0):.2f}\n\n"
                        f"净盈亏: {profit_color}{pnl:+.2f}§r"
                    )

                    def show_panel(p):
                        panel = ActionForm(title=f"结算单 #{pos['id']}", content=content)
                        panel.add_button(
                            "返回仓位历史",
                            on_click=lambda sender: self.show_contract_history_panel(sender)
                        )
                        p.send_form(panel)

                    self._run_for_player(player, show_panel)

                except Exception as e:
                    print(f"加载结算单错误: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self._run_for_player(player, lambda p: p.send_message("§c加载结算单时发生错误"))

            threading.Thread(target=load_data).start()

        except Exception as e:
            print(f"显示结算单错误: {str(e)}")
            player.send_message("§c显示结算单时发生错误")

    def show_contract_teaching_panel(self, player):
        """合约教学页"""
        try:
            fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
            interest_hourly = self.plugin.setting_manager.get_contract_interest_hourly()
            maintenance_rate = self.plugin.setting_manager.get_contract_maintenance_rate()
            liquidation_fee = self.plugin.setting_manager.get_contract_liquidation_fee_rate()
            leverage_options = self.plugin.setting_manager.get_contract_leverage_options()

            content = f'''§h=== 合约交易（做空/杠杆）教学 ===

§6什么是合约？
§a合约让你不必全款买股票，而是投入一部分§e保证金§a，借入其余资金放大涨跌收益。看涨开§a多§a，看跌开§c空§a。

§6核心概念：
§a• 保证金：开仓锁定的本金，仓位价值 = 保证金 × 杠杆
§a• 杠杆：本服可选 {leverage_options} 倍，越高波动越剧烈
§a• 利息：按小时对借入部分收取 {interest_hourly}%%，持仓越久扣得越多
§a• 强平：权益跌到保证金的 {maintenance_rate:.0f}%% 时系统强制平仓，另收 {liquidation_fee}%% 强平费

§6举个例子：
§a投入 $100 保证金，5x 杠杆开多价值 $500 的股票。
§a股价涨 2%% → 赚 $10（本金的 10%%）
§a股价跌 2%% → 亏 $10；跌约 18%% → 爆仓，保证金几乎归零

§6费用说明：
§a• 开仓/平仓各收 {fee_rate}%% 手续费（按仓位价值）
§a• 做空方向风险更大：股价上涨没有上限

§6安全须知：
§a• 逐仓模式：爆仓最多亏掉该笔保证金，不连累余额
§a• 临近强平可在仓位详情页追加保证金自救，强平价会拉远
§a• 强平检测每数十秒一轮，存在延迟，不要贴着强平线持仓
§a• 建议单笔保证金不超过余额的 20%%，预留资金应对波动'''

            panel = ActionForm(
                title="合约教学",
                content=content
            )

            panel.add_button(
                "返回教学指引",
                on_click=lambda sender: self.show_help_panel(sender)
            )

            panel.add_button(
                "返回合约中心",
                on_click=lambda sender: self.show_contract_center(sender)
            )

            player.send_form(panel)

        except Exception as e:
            print(f"显示合约教学面板错误: {str(e)}")
            player.send_message("§c显示合约教学时发生错误")

    # ==================== 历史订单面板 ====================
    def show_orders_panel(self, player, page: int = 0):
        """显示历史订单面板"""
        try:
            xuid = player.xuid
            orders = self.plugin.stock_dao.get_orders(xuid, page=page, page_size=10)
            
            if not orders:
                no_orders_form = ActionForm(
                    title="历史订单",
                    content="您还没有任何订单记录",
                    on_close=lambda sender: self.show_main_panel(sender)
                )
                player.send_form(no_orders_form)
                return
            
            # 构建订单列表
            content = "=== 历史订单 ===\n\n"
            
            order_type_dict = {
                "buy_flex": "市价买入",
                "buy_fix": "限价买入",
                "sell_flex": "市价卖出",
                "sell_fix": "限价卖出",
                "contract_open_long": "合约开多",
                "contract_open_short": "合约开空",
                "contract_close": "合约平仓",
                "contract_liquidation": "合约强平",
                "contract_add_margin": "合约追加保证金"
            }
            
            for order in orders:
                content += f"订单#{order['id']}\n"
                content += f"  {order_type_dict.get(order['type'], order['type'])}\n"
                content += f"  股票: {order['stock_name']} | 股数: {order['share']}\n"
                content += f"  单价: ${order['single_price']:.2f} | 总价: ${order['total']:.2f}\n"
                content += f"  手续费: ${order['tax']:.2f}\n\n"
            
            orders_panel = ActionForm(
                title="历史订单",
                content=content
            )
            
            # 如果有下一页，添加按钮
            if len(orders) >= 10:
                orders_panel.add_button(
                    "下一页",
                    on_click=lambda sender: self.show_orders_panel(sender, page + 1)
                )
            
            # 如果不是第一页，添加上一页按钮
            if page > 0:
                orders_panel.add_button(
                    "上一页",
                    on_click=lambda sender: self.show_orders_panel(sender, page - 1)
                )
            
            # 添加返回按钮
            orders_panel.add_button(
                "返回主菜单",
                on_click=lambda sender: self.show_main_panel(sender)
            )
            
            player.send_form(orders_panel)
            
        except Exception as e:
            print(f"显示订单面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示订单面板时发生错误")
    
    # ==================== 账户管理面板 ====================
    def show_account_panel(self, player):
        """显示账户管理面板"""
        try:
            xuid = player.xuid
            balance = self.plugin.stock_dao.get_balance(xuid)
            game_balance = self.plugin.economy_plugin.get_player_money(player)
            
            content = f"=== 账户管理 ===\n\n"
            content += f"股票账户余额: ${balance:.2f}\n"
            content += f"游戏币余额: ${game_balance:.2f}\n\n"
            content += f"您可以在股票账户和游戏账户之间转账"
            
            account_panel = ActionForm(
                title="账户管理",
                content=content
            )
            
            account_panel.add_button(
                "从游戏账户转入",
                on_click=lambda sender: self.show_transfer_in_panel(sender)
            )
            
            account_panel.add_button(
                "转出到游戏账户",
                on_click=lambda sender: self.show_transfer_out_panel(sender)
            )
            
            account_panel.add_button(
                "返回主菜单",
                on_click=lambda sender: self.show_main_panel(sender)
            )
            
            player.send_form(account_panel)
            
        except Exception as e:
            print(f"显示账户管理面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示账户管理面板时发生错误")
    
    def show_transfer_in_panel(self, player):
        """显示转入面板"""
        game_balance = self.plugin.economy_plugin.get_player_money(player)
        
        transfer_form = ModalForm(
            title="转入资金",
            controls=[
                Label(text=f"从游戏账户转入股票账户\n\n游戏币余额: ${game_balance:.2f}"),
                TextInput(
                    label="转入金额",
                    placeholder="请输入要转入的金额...",
                    default_value=""
                )
            ],
            on_submit=lambda sender, json_str: self._handle_transfer_in(sender, json_str),
            on_close=lambda sender: self.show_account_panel(sender)
        )
        player.send_form(transfer_form)
    
    def _handle_transfer_in(self, player, json_str: str):
        """处理转入"""
        try:
            data = json.loads(json_str)
            amount_str = data[1]
            
            try:
                amount = float(amount_str)
                if amount <= 0:
                    raise ValueError()
            except:
                player.send_message("§c请输入有效的金额（大于0的数字）")
                self.show_transfer_in_panel(player)
                return
            
            # 检查余额
            game_balance = self.plugin.economy_plugin.get_player_money(player)
            if game_balance < amount:
                player.send_message(f"§c游戏币余额不足，当前余额: ${game_balance:.2f}")
                self.show_transfer_in_panel(player)
                return
            
            # 执行转账
            self.plugin.economy_plugin.decrease_player_money(player, amount)
            self.plugin.stock_dao.increase_balance(player.xuid, amount, is_transfer_in=True)
            
            player.send_message(f"§a成功转入 ${amount:.2f} 到股票账户")
            self.show_account_panel(player)
            
        except Exception as e:
            print(f"转入错误: {str(e)}")
            player.send_message("§c转入时发生错误")
    
    def show_transfer_out_panel(self, player):
        """显示转出面板"""
        stock_balance = self.plugin.stock_dao.get_balance(player.xuid)
        
        transfer_form = ModalForm(
            title="转出资金",
            controls=[
                Label(text=f"从股票账户转出到游戏账户\n\n股票账户余额: ${stock_balance:.2f}"),
                TextInput(
                    label="转出金额",
                    placeholder="请输入要转出的金额...",
                    default_value=""
                )
            ],
            on_submit=lambda sender, json_str: self._handle_transfer_out(sender, json_str),
            on_close=lambda sender: self.show_account_panel(sender)
        )
        player.send_form(transfer_form)
    
    def _handle_transfer_out(self, player, json_str: str):
        """处理转出"""
        try:
            data = json.loads(json_str)
            amount_str = data[1]
            
            try:
                amount = float(amount_str)
                if amount <= 0:
                    raise ValueError()
            except:
                player.send_message("§c请输入有效的金额（大于0的数字）")
                self.show_transfer_out_panel(player)
                return
            
            # 检查余额
            stock_balance = self.plugin.stock_dao.get_balance(player.xuid)
            if stock_balance < amount:
                player.send_message(f"§c股票账户余额不足，当前余额: ${stock_balance:.2f}")
                self.show_transfer_out_panel(player)
                return
            
            # 执行转账
            self.plugin.stock_dao.decrease_balance(player.xuid, amount, is_transfer_out=True)
            self.plugin.economy_plugin.increase_player_money(player, amount)
            
            player.send_message(f"§a成功转出 ${amount:.2f} 到游戏账户")
            self.show_account_panel(player)
            
        except Exception as e:
            print(f"转出错误: {str(e)}")
            player.send_message("§c转出时发生错误")
    
    # ==================== 个人设置面板 ====================
    def show_player_settings_panel(self, player):
        """显示个人设置面板"""
        try:
            xuid = player.xuid
            
            # 获取当前配色方案
            current_scheme = self.plugin.player_settings_manager.get_color_scheme(xuid)
            scheme_text = "红涨绿跌（中国习惯）" if current_scheme == 'red_up' else "绿涨红跌（美国习惯）"
            
            content = f"=== 个人设置 ===\n\n"
            content += f"当前配色方案: {scheme_text}\n\n"
            content += f"说明:\n"
            content += f"- 红涨绿跌: 中国股市习惯，上涨显示红色\n"
            content += f"- 绿涨红跌: 美国股市习惯，上涨显示绿色\n\n"
            content += f"选择一个配色方案:"
            
            settings_panel = ActionForm(
                title="个人设置",
                content=content
            )
            
            settings_panel.add_button(
                "红涨绿跌（中国）",
                on_click=lambda sender: self._set_color_scheme(sender, 'red_up')
            )
            
            settings_panel.add_button(
                "绿涨红跌（美国）",
                on_click=lambda sender: self._set_color_scheme(sender, 'green_up')
            )
            
            settings_panel.add_button(
                "返回主菜单",
                on_click=lambda sender: self.show_main_panel(sender)
            )
            
            player.send_form(settings_panel)
            
        except Exception as e:
            print(f"显示个人设置面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("显示个人设置面板时发生错误")
    
    def _set_color_scheme(self, player, scheme: str):
        """设置配色方案"""
        xuid = player.xuid
        
        if self.plugin.player_settings_manager.set_color_scheme(xuid, scheme):
            scheme_text = "红涨绿跌" if scheme == 'red_up' else "绿涨红跌"
            player.send_message(f"已设置配色方案为: {scheme_text}")
        else:
            player.send_message("设置配色方案失败")
        
        # 返回设置面板
        self.show_player_settings_panel(player)
    
    # ==================== 排行榜面板 ====================
    def show_leaderboard_menu(self, player):
        """显示排行榜菜单"""
        try:
            content = "=== 盈亏排行榜 ===\n\n"
            content += "选择要查看的排行榜类型:\n\n"
            content += "- 绝对盈亏: 按赚/亏的金额排序\n"
            content += "- 相对盈亏: 按盈亏百分比排序"
            
            menu_panel = ActionForm(
                title="盈亏排行榜",
                content=content
            )
            
            menu_panel.add_button(
                "绝对盈亏榜",
                on_click=lambda sender: self.show_absolute_leaderboard(sender)
            )
            
            menu_panel.add_button(
                "相对盈亏榜",
                on_click=lambda sender: self.show_relative_leaderboard(sender)
            )
            
            menu_panel.add_button(
                "返回主菜单",
                on_click=lambda sender: self.show_main_panel(sender)
            )
            
            player.send_form(menu_panel)
            
        except Exception as e:
            print(f"显示排行榜菜单错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("显示排行榜菜单时发生错误")
    

    def show_absolute_leaderboard(self, player):
        """显示绝对盈亏排行榜（从插件获取数据）"""
        try:
            xuid = player.xuid
            
            # 从插件获取排行榜数据
            stored_data = self.plugin.get_leaderboard_data(is_absolute=True)
            
            if not stored_data:
                def show_no_data(p):
                    no_data_form = ActionForm(
                        title="绝对盈亏榜",
                        content="暂无数据",
                        on_close=lambda sender: self.show_leaderboard_menu(sender)
                    )
                    p.send_form(no_data_form)
                
                self._run_for_player(player, show_no_data)
                return
            
            # 获取最后更新时间
            last_updated = stored_data[0]['last_updated'] if stored_data else time.time()
            
            # 获取玩家颜色配置
            up_color = self.plugin.player_settings_manager.get_up_color(xuid)
            down_color = self.plugin.player_settings_manager.get_down_color(xuid)
            
            # 构建内容
            content = f"=== 绝对盈亏排行榜 (更新时间: {datetime.datetime.fromtimestamp(last_updated).strftime('%Y-%m-%d %H:%M:%S')} ===\n\n"
            content += "§l§6前5名 (高手榜)§r\n\n"

            top5 = stored_data[:5]
            # 显示前5名
            for data in top5:
                player_name = self._get_player_name(data['player_xuid'])
                profit_loss = data['absolute_profit_loss']
                rank = data.get('rank', '?')
                
                # 使用统一的颜色逻辑
                color = self.plugin.player_settings_manager.get_color_for_change(xuid, profit_loss)
                if profit_loss > 0:
                    sign = "+"
                elif profit_loss < 0:
                    sign = "-"
                else:
                    sign = ""
                
                content += f"#{rank} {player_name}\n"
                content += f"   盈亏: {color}{sign}${abs(profit_loss):.2f}§r\n"
                content += f"   总财富: ${data['total_wealth']:.2f}\n"
            
            # 韭菜榜 = 全服倒数最多5名（排除已在高手榜出现的玩家，避免人少时重复）
            bottom5 = []
            if len(stored_data) > 5:
                top_xuids = {d['player_xuid'] for d in top5}
                bottom5 = [
                    d for d in stored_data[-5:]
                    if d['player_xuid'] not in top_xuids
                ]
                bottom5.reverse()  # 最差的排前面

            if bottom5:
                content += "\n§l§7倒数5名 (韭菜榜)§r\n\n"
                for data in bottom5:
                    player_name = self._get_player_name(data['player_xuid'])
                    profit_loss = data['absolute_profit_loss']
                    rank = data.get('rank', '?')
                    
                    # 使用统一的颜色逻辑
                    color = self.plugin.player_settings_manager.get_color_for_change(xuid, profit_loss)
                    if profit_loss > 0:
                        sign = "+"
                    elif profit_loss < 0:
                        sign = "-"
                    else:
                        sign = ""
                    
                    content += f"#{rank} {player_name}\n"
                    content += f"   盈亏: {color}{sign}${abs(profit_loss):.2f}§r\n"
                    content += f"   总财富: ${data['total_wealth']:.2f}\n"
            
            # 在主线程显示UI
            def show_panel(p):
                leaderboard_panel = ActionForm(
                    title="绝对盈亏榜",
                    content=content
                )
                
                leaderboard_panel.add_button(
                    "返回排行榜菜单",
                    on_click=lambda sender: self.show_leaderboard_menu(sender)
                )
                
                p.send_form(leaderboard_panel)
            
            self._run_for_player(player, show_panel)
            
        except Exception as e:
            print(f"加载绝对盈亏排行榜数据错误: {str(e)}")
            import traceback
            traceback.print_exc()
            self._run_for_player(player, lambda p: p.send_message("显示绝对盈亏排行榜时发生错误"))


    def show_relative_leaderboard(self, player):
        """显示相对盈亏排行榜（从插件获取数据）"""
        try:
            xuid = player.xuid
            
            # 从插件获取排行榜数据
            stored_data = self.plugin.get_leaderboard_data(is_absolute=False)
            
            if not stored_data:
                def show_no_data(p):
                    no_data_form = ActionForm(
                        title="相对盈亏榜",
                        content="暂无数据",
                        on_close=lambda sender: self.show_leaderboard_menu(sender)
                    )
                    p.send_form(no_data_form)
                
                self._run_for_player(player, show_no_data)
                return
            
            # 获取最后更新时间
            last_updated = stored_data[0]['last_updated'] if stored_data else time.time()
            
            # 获取玩家颜色配置
            up_color = self.plugin.player_settings_manager.get_up_color(xuid)
            down_color = self.plugin.player_settings_manager.get_down_color(xuid)
            
            # 构建内容
            content = f"=== 相对盈亏排行榜 (更新时间: {datetime.datetime.fromtimestamp(last_updated).strftime('%Y-%m-%d %H:%M:%S')} ===\n\n"
            content += "§l§6前5名 (高手榜)§r\n\n"
            
            top5 = stored_data[:5]
            # 显示前5名
            for data in top5:
                player_name = self._get_player_name(data['player_xuid'])
                profit_loss_percent = data['relative_profit_loss']
                profit_loss = data['absolute_profit_loss']
                rank = data.get('rank', '?')
                
                # 使用统一的颜色逻辑
                color = self.plugin.player_settings_manager.get_color_for_change(xuid, profit_loss)
                if profit_loss_percent > 0:
                    sign = "+"
                elif profit_loss_percent < 0:
                    sign = "-"
                else:
                    sign = ""
                
                content += f"#{rank} {player_name}\n"
                content += f"   收益率: {color}{sign}{abs(profit_loss_percent):.2f}%%§r\n"
                content += f"   盈亏: {color}{sign}${abs(profit_loss):.2f}§r\n\n"
            
            # 接盘侠 = 全服倒数最多5名（排除已在高手榜出现的玩家）
            bottom5 = []
            if len(stored_data) > 5:
                top_xuids = {d['player_xuid'] for d in top5}
                bottom5 = [
                    d for d in stored_data[-5:]
                    if d['player_xuid'] not in top_xuids
                ]
                bottom5.reverse()

            if bottom5:
                content += "§l§7倒数5名 (接盘侠榜)§r\n\n"
                for data in bottom5:
                    player_name = self._get_player_name(data['player_xuid'])
                    profit_loss_percent = data['relative_profit_loss']
                    profit_loss = data['absolute_profit_loss']
                    rank = data.get('rank', '?')
                    
                    # 使用统一的颜色逻辑
                    color = self.plugin.player_settings_manager.get_color_for_change(xuid, profit_loss)
                    if profit_loss_percent > 0:
                        sign = "+"
                    elif profit_loss_percent < 0:
                        sign = "-"
                    else:
                        sign = ""
                    
                    content += f"#{rank} {player_name}\n"
                    content += f"   收益率: {color}{sign}{abs(profit_loss_percent):.2f}%%§r\n"
                    content += f"   盈亏: {color}{sign}${abs(profit_loss):.2f}§r\n\n"
            
            # 在主线程显示UI
            def show_panel(p):
                leaderboard_panel = ActionForm(
                    title="相对盈亏榜",
                    content=content
                )
                
                leaderboard_panel.add_button(
                    "返回排行榜菜单",
                    on_click=lambda sender: self.show_leaderboard_menu(sender)
                )
                
                p.send_form(leaderboard_panel)
            
            self._run_for_player(player, show_panel)
            
        except Exception as e:
            print(f"加载相对盈亏排行榜数据错误: {str(e)}")
            import traceback
            traceback.print_exc()
            self._run_for_player(player, lambda p: p.send_message("显示相对盈亏排行榜时发生错误"))
    
    
    def _get_player_name(self, player_xuid: str) -> str:
        """
        根据XUID获取玩家名称
        :param player_xuid: 玩家XUID
        :return: 玩家名称，如果获取不到则返回XUID前8位
        """
        try:
            # 使用arc_core插件获取玩家名称
            arc_core = self.plugin.server.plugin_manager.get_plugin('arc_core')
            if arc_core:
                player_name = arc_core.get_player_name_by_xuid(player_xuid)
                if player_name:
                    return player_name
            
            # 如果获取失败，返回XUID的前8位作为标识
            return f"玩家{player_xuid[:8]}"
        except:
            return f"玩家{player_xuid[:8]}"
    
    # ==================== 教学指引面板 ====================
    def show_help_panel(self, player):
        """显示教学指引面板"""
        try:
            # 获取当前手续费率
            fee_rate = self.plugin.setting_manager.get_trading_fee_rate()
            
            help_content = f'''§c警告：本插件为模拟美股交易插件，您的所有操作均为模拟操作，不会产生真实交易。您只能将股票买卖的利润转为游戏币，您永远无法将其提现为现实中可交易的货币。

§6欢迎来到"荣辱浮沉 (Ups and Downs)" 股票插件，在这里，你可以让自己的财富名列服务器榜首，又或者跟随某个臭名昭著的企业的股票一夜蒸发。

§6这里的一切股票价格都跟实时同步美股市场，所以我强烈推荐你用现实中的股票软件选股和盯盘。股票价格是非常珍贵的数据，我们所提供的数据也仅供参考。

§6如果你不会查股票？那我建议你学起来，毕竟在这里验证你的智商后，你也会迈向亏光家产，哦不，我是说盆满钵满的那一天，你说对吧？

§h=== 股票基础知识 ===

§a• 股票价格：反映市场对公司价值的评估
§a• 成交量：交易活跃度，量大说明关注度高
§a• 基本面：公司财务状况、盈利能力等
§a• 技术面：价格走势、图表形态等
§a• 消息面：新闻、公告对股价的影响

§h=== 交易策略 ===

§a• 价值投资：买入被低估的优质公司
§a• 趋势交易：跟随价格趋势进行买卖
§a• 短线交易：利用短期价格波动获利
§a• 分散投资：不要把所有资金投入一只股票
§a• 止损止盈：设定合理的盈亏目标

§h=== 风险提示 ===

§a• 股市有风险，投资需谨慎
§a• 不要借钱炒股，只用闲钱投资
§a• 保持冷静，不要被情绪左右
§a• 学习为主，盈利为辅

§h=== 功能说明 ===

§a• 手续费：每笔交易收取{fee_rate}%%手续费
§a• 市价单：按当前市场价格立即成交
§a• 限价单：指定价格，只有价格合适时才成交
§a• 时间范围：支持查看10分钟、10天、10个月的价格走势
§a• 合约交易：支持做空与杠杆（逐仓），详见合约教学

§s提示：建议使用专业股票软件查询最新价格'''

            help_panel = ActionForm(
                title="教学指引",
                content=help_content
            )

            help_panel.add_button(
                "合约交易教学(做空/杠杆)",
                on_click=lambda sender: self.show_contract_teaching_panel(sender)
            )

            help_panel.add_button(
                "基础知识详解",
                on_click=lambda sender: self.show_basic_knowledge_panel(sender)
            )
            
            help_panel.add_button(
                "交易技巧进阶",
                on_click=lambda sender: self.show_trading_tips_panel(sender)
            )
            
            help_panel.add_button(
                "风险管理指南",
                on_click=lambda sender: self.show_risk_management_panel(sender)
            )
            
            help_panel.add_button(
                "返回主菜单",
                on_click=lambda sender: self.show_main_panel(sender)
            )
            
            player.send_form(help_panel)
            
        except Exception as e:
            print(f"显示教学指引面板错误: {str(e)}")
            import traceback
            traceback.print_exc()
            player.send_message("§c显示教学指引时发生错误")
    
    def show_basic_knowledge_panel(self, player):
        """显示基础知识详解面板"""
        try:
            content = '''§h=== 股票基础知识详解 ===

§6什么是股票？
§a股票是公司所有权的凭证，持有股票就是公司的股东。

§6股票价格如何决定？
§a• 供需关系：买的人多价格涨，卖的人多价格跌
§a• 公司业绩：盈利增长通常推动股价上涨
§a• 市场情绪：投资者信心影响买卖决策
§a• 宏观经济：经济环境对股市整体影响

§6重要概念解释：
§a• 市值 = 股价 × 总股本
§a• 市盈率 = 股价 ÷ 每股收益
§a• 成交量：某时间段内的交易数量
§a• 换手率：成交量 ÷ 流通股本

§6基本面分析：
§a• 财务报表：收入、利润、负债等
§a• 行业地位：公司在行业中的竞争力
§a• 管理层：公司领导层的能力和诚信
§a• 发展前景：公司未来增长潜力

§6技术面分析：
§a• K线图：显示价格走势的图表
§a• 支撑位：价格下跌时的支撑点
§a• 阻力位：价格上涨时的阻力点
§a• 趋势线：价格运行的主要方向

§s记住：投资需要不断学习，理论与实践相结合！'''
            
            panel = ActionForm(
                title="基础知识详解",
                content=content
            )
            
            panel.add_button(
                "返回教学指引",
                on_click=lambda sender: self.show_help_panel(sender)
            )
            
            player.send_form(panel)
            
        except Exception as e:
            print(f"显示基础知识面板错误: {str(e)}")
            player.send_message("§c显示基础知识时发生错误")
    
    def show_trading_tips_panel(self, player):
        """显示交易技巧进阶面板"""
        try:
            content = '''§h=== 交易技巧进阶 ===

§6买入时机选择：
§a• 低位买入：价格相对较低时买入
§a• 突破买入：价格突破重要阻力位时
§a• 回调买入：上涨趋势中的回调机会
§a• 消息面买入：利好消息发布后

§6卖出时机选择：
§a• 高位卖出：价格相对较高时卖出
§a• 止损卖出：价格跌破支撑位时
§a• 获利了结：达到预期收益目标
§a• 消息面卖出：利空消息发布后

§6订单类型使用：
§a• 市价单：急于成交时使用
§a• 限价单：希望控制成交价格时
§a• 止损单：自动止损保护资金
§a• 止盈单：自动获利了结

§6资金管理技巧：
§a• 分批建仓：不要一次性全仓买入
§a• 仓位控制：单只股票不超过总资金的30%%
§a• 加仓策略：盈利时适当加仓
§a• 减仓策略：亏损时及时减仓

§6心理控制：
§a• 保持冷静：不要被情绪左右
§a• 制定计划：按计划执行交易
§a• 接受亏损：亏损是交易的一部分
§a• 持续学习：不断提升交易技能

§s记住：没有完美的交易策略，适合自己的才是最好的！'''
            
            panel = ActionForm(
                title="交易技巧进阶",
                content=content
            )
            
            panel.add_button(
                "返回教学指引",
                on_click=lambda sender: self.show_help_panel(sender)
            )
            
            player.send_form(panel)
            
        except Exception as e:
            print(f"显示交易技巧面板错误: {str(e)}")
            player.send_message("§c显示交易技巧时发生错误")
    
    def show_risk_management_panel(self, player):
        """显示风险管理指南面板"""
        try:
            content = '''§h=== 风险管理指南 ===

§c风险警示：
§4股市有风险，投资需谨慎！本插件仅为模拟交易，请勿将虚拟经验直接应用于真实投资。

§6主要风险类型：
§a• 市场风险：整体市场下跌的风险
§a• 个股风险：单只股票价格波动的风险
§a• 流动性风险：无法及时买卖的风险
§a• 政策风险：政策变化对股市的影响

§6风险管理原则：
§a• 分散投资：不要把所有资金投入一只股票
§a• 控制仓位：单只股票不超过总资金的30%%
§a• 设置止损：为每笔交易设定最大亏损额度
§a• 分批建仓：避免一次性全仓买入

§6止损策略：
§a• 固定止损：设定固定的亏损比例
§a• 技术止损：基于技术分析设定止损位
§a• 时间止损：设定持仓时间限制
§a• 情绪止损：当情绪失控时及时退出

§6资金管理：
§a• 只用闲钱：不要借钱或使用生活必需资金
§a• 控制杠杆：避免过度使用杠杆
§a• 保留现金：始终保持一定的现金储备
§a• 定期评估：定期评估投资组合风险

§6心理管理：
§a• 保持理性：不要被贪婪和恐惧控制
§a• 接受亏损：亏损是交易的一部分
§a• 控制情绪：避免情绪化交易
§a• 持续学习：不断提升风险管理能力

§s记住：保护本金比追求高收益更重要！'''
            
            panel = ActionForm(
                title="风险管理指南",
                content=content
            )
            
            panel.add_button(
                "返回教学指引",
                on_click=lambda sender: self.show_help_panel(sender)
            )
            
            player.send_form(panel)
            
        except Exception as e:
            print(f"显示风险管理面板错误: {str(e)}")
            player.send_message("§c显示风险管理时发生错误")
