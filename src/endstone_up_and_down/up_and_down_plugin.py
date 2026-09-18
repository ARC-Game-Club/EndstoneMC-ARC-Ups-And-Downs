import datetime
import time
from decimal import *
import threading
import random
from typing import Union


from endstone.command import Command, CommandSender
from endstone.event import EventPriority, ServerLoadEvent, event_handler
from endstone.plugin import Plugin
import yfinance as yf

from endstone_up_and_down.databaseManager import DatabaseManager
from endstone_up_and_down.customWebsocket import CustomWebsocket
from endstone_up_and_down.stockDao import StockDao
from endstone_up_and_down.lockManager import LockException, LockManager, LockWithTimeout
from endstone_up_and_down.marketStatusListenr import MarketStatusListener
from endstone_up_and_down.favorites_manager import FavoritesManager
from endstone_up_and_down.ui_manager import UIManager
from endstone_up_and_down.setting_manager import StockSettingManager
from endstone_up_and_down.player_settings_manager import PlayerSettingsManager


class UpAndDownPlugin(Plugin):
    prefix = "UpAndDown"
    api_version = "0.6"
    load = "POSTWORLD"
    
    # 插件数据目录
    MAIN_PATH = "plugins/UpAndDown"

    commands = {
        "stock":{
                    "description": "股票插件，使用/stock help获取帮助",
                    "usages": ["/stock show [stockName: string] [period: string]",
                               "/stock account",
                               "/stock transferin [amount:int]",
                               "/stock transferout [amount:int]",
                               "/stock buy [stockName: string] [share:int] [price:float]",
                               "/stock sell [stockName: string] [share:int] [price:float]",
                               "/stock long [stockName: string] [margin:float] [leverage:int]",
                               "/stock short [stockName: string] [margin:float] [leverage:int]",
                               "/stock close [positionId:int] [share:int]",
                               "/stock margin [positionId:int] [amount:float]",
                               "/stock positions [page:int]",
                               "/stock orders [page:int]",
                               "/stock help",
                               "/stock shares",
                               "/stock ui"
                               ],
                    "permissions": ["up_and_down.command.transaction"]
                }
    }

    permissions = {
        "up_and_down.command.transaction": {
            "description": "Working on it",
            "default": True,
        }
    }
    
    order_type_dict = {
        "buy_flex": "市价单购买",
        "buy_fix": "限价单购买",
        "sell_flex": "市价单出售",
        "sell_fix": "限价单出售",
        "contract_open_long": "合约开多",
        "contract_open_short": "合约开空",
        "contract_close": "合约平仓",
        "contract_liquidation": "合约强平",
        "contract_add_margin": "合约追加保证金"
    }

    def on_load(self) -> None:
        # 初始化配置管理器
        self.setting_manager = StockSettingManager(self.MAIN_PATH)
        # 合约配置项连同默认值落盘，便于服主调整
        self.setting_manager.ensure_contract_config()
        
        # 配置 yfinance 代理
        enable_proxy, proxy_address = self.setting_manager.get_proxy_config()
        if enable_proxy and proxy_address:
            yf.set_config(proxy=proxy_address)
            self.logger.info(f"§e已启用代理: {proxy_address}")
        else:
            self.logger.info("§e未启用代理")
            yf.set_config(proxy=None)
            
        # 测试 yfinance 连接
        try:
            test_price, tradeable = self.get_stock_last_price("NIO")
            if test_price:
                self.logger.info(f"§a[成功] yfinance连接测试成功！NIO当前股票价格: ${test_price}")
            else:
                self.logger.warning("§c[失败] yfinance连接测试失败：无法获取NIO的股票价格")
        except Exception as e:
            self.logger.error(f"§c[错误] yfinance连接测试失败: {str(e)}")
        
        # 设置数据库路径
        import os
        db_path = os.path.join(self.MAIN_PATH, "up_and_down.db")
        
        self.database_manager = DatabaseManager(db_path)
        self.stock_dao = StockDao(self.database_manager)
        self.stock_dao.init_tables()
        self.lock_manager = LockManager()
        
        # 初始化收藏夹管理器、玩家设置管理器和UI管理器
        self.favorites_manager = FavoritesManager(self.database_manager)
        self.player_settings_manager = PlayerSettingsManager(self.database_manager)
        self.ui_manager = UIManager(self)
        
        self.logger.info("§e Up and down Loaded!")
        # self.market_state_listener = MarketStatusListener("AAPL")
        # self.market_state_listener.start_listen()
        

    def on_enable(self) -> None:
        # Schedule leaderboard update every 30 minutes
        self.server.scheduler.run_task(
            self, 
            self.update_leaderboard, 
            delay=0, 
            period=20 * 60 * 30
        )

        # 合约强平/预警检测任务
        contract_interval = self.setting_manager.get_contract_check_interval()
        self.server.scheduler.run_task(
            self,
            self.check_contract_positions,
            delay=20 * 15,
            period=20 * contract_interval
        )

        self.economy_plugin = self.server.plugin_manager.get_plugin('arc_core')
        self.qqsync = self._get_qq_sync_plugin()
        self._register_arc_main_menu_button()

    def _register_arc_main_menu_button(self) -> None:
        core = getattr(self, "economy_plugin", None)
        if core is None or not hasattr(core, "api_register_main_menu_button"):
            return
        try:
            core.api_register_main_menu_button(
                "up_and_down:main",
                "证券交易所",
                on_click=lambda p: p.perform_command("stock ui"),
                priority=6,
                icon="textures/arc_core/stock.png",
            )
        except Exception:
            pass

    def _get_qq_sync_plugin(self):
        """Resolve ARC QQ Sync plugin (AstrBot hub id first, legacy id fallback).

        Endstone 会把 entry-point 里的 '-' 转成 '_'，故优先查找 arc_qq_sync_astrbot。
        """
        pm = self.server.plugin_manager
        for name in (
            "arc_qq_sync_astrbot",
            "arc-qq-sync-astrbot",
            "qqsync_plugin",
        ):
            plug = pm.get_plugin(name)
            if plug is not None:
                return plug
        return None


    def on_disable(self) -> None:
        try:
            core = self.server.plugin_manager.get_plugin("arc_core")
            if core is not None and hasattr(core, "api_unregister_main_menu_button"):
                core.api_unregister_main_menu_button("up_and_down:main")
        except Exception:
            pass

    def _extract_player_name(self, name: str) -> str:
        """
        从可能包含格式代码的名称中提取真实玩家名
        例如: §c[主宰]§rDEVILENMO -> DEVILENMO
        """
        if "§r" in name:
            return name.split("§r")[-1]
        return name

    def execute_command(self, sender: CommandSender, args: list[str], return_value:bool, callback=None, callback_args=None):
        player_name = self._extract_player_name(sender.name)
        print(f"sender name {sender.name} -> {player_name}, execute_command: {args}")
        def command_executor():
            try:
                # 处理UI命令（不需要线程处理）
                if args[0] == "ui":
                    player = self.server.get_player(player_name)
                    if player:
                        self.ui_manager.show_main_panel(player)
                    else:
                        sender.send_message("§c只有玩家可以使用UI面板")
                    return
                
                player = self.server.get_player(player_name)
                xuid = player.xuid
                
                if args[0] != "transferin":
                    if not self.stock_dao.check_user_account(xuid):
                        sender.send_message(f"§e请先使用transferin转入初始资金以激活股票账户")
                        return
                
                command_dict = {
                    "show": self.show,
                    "buy": self.buy_stock,
                    "sell": self.sell_stock,
                    "long": self.open_long_cmd,
                    "short": self.open_short_cmd,
                    "close": self.close_contract_cmd,
                    "margin": self.add_margin_cmd,
                    "positions": self.show_positions_cmd,
                    "transferin": self.transfer_in,
                    "transferout": self.transfer_out,
                    "account": self.my_account,
                    "help": self.help,
                    "orders": self.show_orders,
                    "shares": self.show_shares
                }

                require_lock_command_list = ['buy', 'sell', 'long', 'short', 'close', 'margin', 'transferin', 'transferout']
                
                command_func = command_dict[args[0]]
                
                if args[0] in require_lock_command_list:
                    player_lock = self.lock_manager.get_player_lock(str(xuid))
                    try:
                        with LockWithTimeout(player_lock, 1):
                            rtn = command_func(xuid, sender, args)
                    except LockException as ex:
                        sender.send_error_message("当前账号有其他股票操作正在进行，请稍候操作")
                else:
                    rtn = command_func(xuid, sender, args)
                
                if return_value:
                    xuid = str(getattr(player, "xuid", "") or "").strip()
                    name = str(getattr(player, "name", "") or "").strip() or player_name
                    result = rtn

                    def _callback_on_main() -> None:
                        p = self.ui_manager._resolve_online_player(xuid, name)
                        if p is None:
                            return
                        callback(result, p, callback_args)

                    self.server.scheduler.run_task(
                        self,
                        _callback_on_main,
                        delay=0,
                    )
                
            except Exception as e:
                import traceback
                exception = e
                exception_msg = str(e)
                full_traceback = traceback.format_exc()

                print("Exception Object:", exception)
                print("Exception Message:", exception_msg)
                print("Full Traceback:")
                print(full_traceback)
                
                sender.send_message(f"Exception Object:{exception}")
                sender.send_message(f"Exception Message:{exception_msg}")
                sender.send_message("Full Traceback:")
                sender.send_message(f"{full_traceback}")

        if return_value and callback == None:
            raise Exception("Callback function must not be None if return value is true, Fool!")

        if args[0] == "ui":
            command_executor()
        else:
            thread = threading.Thread(target=command_executor)
            thread.start()

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        '''
            Command router
        '''
        self.execute_command(sender, args, False)

        

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    #
    #                     Common Utils
    #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 


    def is_available(self, ticket):
        info = ticket.info
        if ticket.ticker == "BTC-USD":
            return True
        
        return info['market'] in ['us_market'] 

    def get_stock_last_price(self, stock, period="1d", interval="1m", return_period=False):
        '''
            Return price, tradeable
        '''

        ticket = yf.Ticker(stock)

        if not self.is_available(ticket):
            return None, None

        df = ticket.history(period=period, interval=interval, prepost=True)

        if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
            return None, None
        
        if return_period:
            return list(df["Close"]), True
        
        price = round(df.Close.iloc[-1], 2)
        price = Decimal(str(price))
        
        return price, True
    

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    #
    #                     Command Excutors
    #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
    def show(self, xuid, sender, args):
        '''
            Show stock price
        '''

        if len(args) == 2:
            unit = "day"
        else:
            unit = args[2]
        
        if unit == "minute":
            price_list, tradeable = self.get_stock_last_price(args[1], return_period=True)
            unit_zh = "10分钟"
        elif unit == "day":
            price_list, tradeable = self.get_stock_last_price(args[1], period="1mo", interval="1d", return_period=True)
            unit_zh = "10天"
        elif unit == "month":
            price_list, tradeable = self.get_stock_last_price(args[1], period="1y",interval="1mo", return_period=True)
            unit_zh = "10个月"
        else:
            sender.send_message(f"§4时间范围必须是minute, day, month其中之一, 你输入的{unit}无效")
            return
        
        if price_list == None:
            sender.send_message(f"你输入了错误的股票名或该股票市场尚不支持:{args[1]}")
            return
        
            
        
        price_str = f"股票{args[1]} 历史{unit_zh}成交价格: "
        price_list = price_list[-11:]
        
        for idx, price in enumerate(price_list):
            if idx == 0:
                continue
            if price > price_list[idx - 1]:
                price_str += "§c" + str(round(price, 2)) + '\n'
            elif price < price_list[idx - 1]:
                price_str += "§q" + str(round(price, 2)) + '\n'
            else:
                price_str += "§7" + str(round(price)) + '\n'
        price_str += "§e以上数据仅供参考，建议使用专业股票软件查询最新价格"
        
        sender.send_message(price_str)
        
        
    def transfer_in(self, xuid, sender, args):
        amount = float(args[1])
        player_name = self._extract_player_name(sender.name)
        player = self.server.get_player(player_name)
        
        player_balance = self.economy_plugin.get_player_money(player)
        
        if player_balance < amount:
            sender.send_message(f"§e您的经济实力似乎不足以支付 {amount} 元")
            return
            
        self.economy_plugin.decrease_player_money(player, amount)
        self.stock_dao.increase_balance(xuid, amount, is_transfer_in=True)
        
        sender.send_message(f"§e成功向股票账户汇入 {amount} 元")
        
        
    def my_account(self, xuid, sender, args):
        amount = self.stock_dao.get_balance(xuid)
        message = f"§e股票账户余额 {amount} 元"

        # 合约持仓概况（现价拉取失败时降级为只显示占用）
        try:
            positions = self.stock_dao.get_open_margin_positions(xuid)
            if positions:
                locked = Decimal(0)
                unrealized = Decimal(0)
                interest_hourly = self.setting_manager.get_contract_interest_hourly()
                price_cache = {}
                priced = False
                for pos in positions:
                    locked += Decimal(str(pos["margin"]))
                    stock = pos["stock_name"]
                    if stock not in price_cache:
                        try:
                            price_cache[stock] = self.get_stock_last_price(stock)[0]
                        except Exception:
                            price_cache[stock] = None
                    price = price_cache[stock]
                    if not price:
                        continue
                    priced = True
                    pnl, interest = self._calc_contract_pnl_interest(pos, price, interest_hourly)
                    unrealized += pnl - interest
                summary = f"§e合约持仓 {len(positions)} 笔，占用保证金 {float(locked):.2f} 元"
                if priced:
                    summary += f"，浮动盈亏 {float(unrealized):+.2f} 元（已扣应计利息）"
                message += "\n" + summary
        except Exception:
            pass

        sender.send_message(message)
        
    
    def transfer_out(self, xuid, sender, args):
        # 获取转出金额

        amount = float(args[1])

        # 获取玩家对象
        player_name = self._extract_player_name(sender.name)
        player = self.server.get_player(player_name)
        
        # 获取玩家股票账户余额
        stock_balance = self.stock_dao.get_balance(xuid)
        
        # 检查股票账户余额是否足够
        if stock_balance < amount:
            sender.send_message(f"§e您的股票账户余额不足，当前余额: {stock_balance} 元")
            return
        
        # 执行转账操作
        try:
            # 从股票账户扣除金额
            self.stock_dao.decrease_balance(xuid, amount, is_transfer_out=True)
            # 增加玩家游戏账户余额
            self.economy_plugin.increase_player_money(player, amount)
            
            sender.send_message(f"§e成功从股票账户转出 {amount} 元到游戏银行账户")
        except Exception as e:
            # 如果转账过程中出现错误，回滚操作
            sender.send_message("§e转账失败，请稍后重试")
            # 可以在这里添加日志记录
            print(f"Transfer out failed for player {xuid}: {str(e)}")
        
        
    def buy_stock(self, xuid, sender, args) -> Union[bool, str]:
        '''
            Buy stock

            args[0] buy
            args[1] stock_name
            args[2] share
            args[3] [price]

            Return:
            True/False, Message
        '''
        
        player_name = self._extract_player_name(sender.name)
        player = self.server.get_player(player_name)
        stock_name = args[1]
        share = args[2]
        
        # sender.send_message("§6交易正在进行中(预计花费30秒到1分钟)...")
        # time.sleep(random.randrange(30, 60))
        
        market_price, tradeable = self.get_stock_last_price(stock_name)
        if tradeable == None:
            message = f"你输入了错误的股票名或该股票市场尚不支持:{args[1]}"
            sender.send_message(message)
            return False, message
        
        if len(args) == 4:
            price = Decimal(str(args[3]))
            type = "buy_fix"
        else:
            price = Decimal(str(market_price)) if tradeable else Decimal(0)
            sender.send_message(f"市价单单价:{price}")
            type = "buy_flex"
            
        market_type = "实时交易" if tradeable else "盘后交易"
        
        order_id = self.stock_dao.create_order(xuid, stock_name, share, type)
        sender.send_message(f"订单创建成功，订单号: {order_id} 类型: {self.order_type_dict[type]} {market_type}")
        
        if price < market_price:
            message = f"股票购买失败，当前市场价:{market_price}, 没有人愿意按您的报价{price}元交易"
            sender.send_message(message)
            return False, message
        player_balance = self.stock_dao.get_balance(xuid)
        
        share = Decimal(str(share))
        fee_rate = Decimal(str(self.setting_manager.get_trading_fee_rate() / 100))
        tax = price * share * fee_rate
        total_price = price * share + tax
        if player_balance < total_price:
            message = f"您的经济实力似乎不足以支付 {total_price} 元"
            sender.send_message(message)
            return False, message
        self.stock_dao.decrease_balance(xuid, total_price)
        self.stock_dao.buy(order_id, stock_name, xuid, share, price, tax, total_price)

        message = f"股票购买成功，总计:{total_price}元"
        sender.send_message(message)
        return True, message
            
            
    def sell_stock(self, xuid, sender, args) -> Union[bool, str]:
        stock_name = args[1]
        share = Decimal(args[2])
        
        # sender.send_message("§6交易正在进行中(预计花费30秒到1分钟)...")
        # time.sleep(random.randrange(30, 60))

        # 获取股票当前价格和可交易状态
        market_price, tradeable = self.get_stock_last_price(stock_name)
        if tradeable is None:
            message = f"你输入了错误的股票名或该股票市场尚不支持:{args[1]}"
            sender.send_message(message)
            return False, message
        
        # 解析价格参数（限价单或市价单）
        if len(args) == 4:
            price = Decimal(str(args[3]))
            order_type = "sell_fix"
        else:
            price = Decimal(str(market_price)) if tradeable else Decimal(0)
            sender.send_message(f"市价单单价:{price}")
            order_type = "sell_flex"
        
        # 检查玩家持股数量
        current_holding = self.stock_dao.get_player_stock_holding(xuid, stock_name)
        if current_holding < Decimal(share):
            message = f"您的持股不足，当前持有 {current_holding} 股"
            sender.send_message(message)
            return False, message
        
        
        # 创建出售订单
        order_id = self.stock_dao.create_order(xuid, stock_name, share, order_type)
        market_type = "实时交易" if tradeable else "盘后交易"
        sender.send_message(f"订单创建成功，订单号: {order_id} 类型: {self.order_type_dict[order_type]} {market_type}")
        

        # 检查市场价格是否满足限价要求
        if market_price < price:
            message = f"股票出售失败，当前市场价:{market_price}, 没有人愿意按您的报价{price}元购买"
            sender.send_message(message)
            return False, message
        
        # 计算总收入（扣除手续费）
        total_price = price * Decimal(share)
        fee_rate = Decimal(str(self.setting_manager.get_trading_fee_rate() / 100))
        tax = total_price * fee_rate
        net_revenue = total_price - tax
        
        # 执行交易
        self.stock_dao.sell(order_id, stock_name, xuid, share, price, tax, total_price)
        self.stock_dao.increase_balance(xuid, net_revenue)

        message = f"股票出售成功，总计:{net_revenue}元"
        sender.send_message(message)

        return True, message

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    #
    #                Contract (Margin/Short) Executors
    #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def _get_online_player_by_xuid(self, xuid):
        xuid_s = str(xuid or "").strip()
        for p in self.server.online_players or []:
            if str(getattr(p, "xuid", "")) == xuid_s:
                return p
        return None

    @staticmethod
    def _calc_contract_pnl_interest(pos, price, interest_hourly):
        """计算合约仓位浮动盈亏与应计利息，返回 (pnl, interest) Decimal"""
        price = Decimal(str(price))
        entry = Decimal(str(pos["entry_price"]))
        share = Decimal(str(pos["share"]))
        margin = Decimal(str(pos["margin"]))
        if pos["direction"] == "short":
            pnl = (entry - price) * share
        else:
            pnl = (price - entry) * share
        borrowed = max(entry * share - margin, Decimal(0))
        hours = Decimal(str(max(time.time() - float(pos["open_time"]), 0.0) / 3600.0))
        interest = borrowed * Decimal(str(interest_hourly)) / Decimal(100) * hours
        return pnl, interest

    @staticmethod
    def _calc_contract_liquidation_price(pos, maintenance_rate):
        """预估强平价（忽略利息的静态近似）"""
        entry = Decimal(str(pos["entry_price"]))
        margin = Decimal(str(pos["margin"]))
        share = Decimal(str(pos["share"]))
        delta = margin * (Decimal(100) - Decimal(str(maintenance_rate))) / Decimal(100) / share
        if pos["direction"] == "short":
            return entry + delta
        return entry - delta

    def open_long_cmd(self, xuid, sender, args):
        return self.open_contract(xuid, sender, "long", args)

    def open_short_cmd(self, xuid, sender, args):
        return self.open_contract(xuid, sender, "short", args)

    def open_contract(self, xuid, sender, direction, args):
        '''
            开合约仓（逐仓）
            args[1] stock_name, args[2] margin, args[3] [leverage]
            Return: (bool, message)
        '''
        direction_text = "多" if direction == "long" else "空"
        stock_name = args[1]

        try:
            margin_amount = Decimal(str(float(args[2])))
        except Exception:
            message = f"保证金金额无效: {args[2]}"
            sender.send_message(message)
            return False, message

        leverage_options = self.setting_manager.get_contract_leverage_options()
        max_leverage = self.setting_manager.get_contract_max_leverage()
        if len(args) > 3:
            try:
                leverage = int(args[3])
            except Exception:
                message = f"杠杆倍数无效: {args[3]}"
                sender.send_message(message)
                return False, message
        else:
            leverage = leverage_options[0]
        if leverage not in leverage_options:
            message = f"杠杆倍数仅支持 {leverage_options}（上限 {max_leverage}x）"
            sender.send_message(message)
            return False, message

        min_margin = Decimal(str(self.setting_manager.get_contract_min_margin()))
        if margin_amount < min_margin:
            message = f"保证金最低 {min_margin} 元"
            sender.send_message(message)
            return False, message

        market_price, tradeable = self.get_stock_last_price(stock_name)
        if tradeable is None or market_price is None:
            message = f"你输入了错误的股票名或该股票市场尚不支持:{stock_name}"
            sender.send_message(message)
            return False, message

        price = Decimal(str(market_price))
        if price <= 0:
            message = "当前价格异常，无法开仓"
            sender.send_message(message)
            return False, message

        share = int(margin_amount * Decimal(leverage) / price)
        if share < 1:
            message = f"保证金不足：{price} 元的股票 {leverage}x 杠杆至少需要 {price / Decimal(leverage)} 元保证金"
            sender.send_message(message)
            return False, message

        open_value = price * Decimal(share)
        fee_rate = Decimal(str(self.setting_manager.get_trading_fee_rate() / 100))
        open_fee = open_value * fee_rate
        total_cost = margin_amount + open_fee

        balance = self.stock_dao.get_balance(xuid)
        if balance is None or Decimal(str(balance)) < total_cost:
            message = f"余额不足：需 {total_cost:.2f} 元（保证金 {margin_amount:.2f} + 开仓费 {open_fee:.2f}），当前余额 {balance} 元"
            sender.send_message(message)
            return False, message

        order_id = self.stock_dao.create_order(
            xuid, stock_name, share,
            "contract_open_long" if direction == "long" else "contract_open_short"
        )
        self.stock_dao.decrease_balance(xuid, total_cost)
        position_id = self.stock_dao.create_margin_position(
            xuid, stock_name, direction, leverage, margin_amount, share, price, open_fee
        )
        self.stock_dao.finish_order(order_id, price, open_fee, open_fee)

        liq_price_text = "获取失败"
        new_pos = self.stock_dao.get_margin_position(position_id) if position_id else None
        if new_pos:
            liq_price = self._calc_contract_liquidation_price(
                new_pos, self.setting_manager.get_contract_maintenance_rate()
            )
            liq_price_text = f"${float(liq_price):.2f}"
        message = (
            f"§a合约开{direction_text}成功！仓位号 #{position_id}\n"
            f"§e{stock_name} {leverage}x | {share}股 @ ${float(price):.2f} | 仓位价值 ${float(open_value):.2f}\n"
            f"§e占用保证金 {float(margin_amount):.2f} 元 + 开仓费 {float(open_fee):.2f} 元\n"
            f"§c预估强平价 {liq_price_text}（权益随利息消耗，强平以实时检测为准）"
        )
        sender.send_message(message)
        return True, message

    def close_contract_cmd(self, xuid, sender, args):
        '''
            平仓 /stock close <仓位ID> [股数]
        '''
        try:
            position_id = int(args[1])
        except Exception:
            message = f"仓位号无效: {args[1] if len(args) > 1 else ''}"
            sender.send_message(message)
            return False, message

        share_to_close = None
        if len(args) > 2:
            try:
                share_to_close = int(args[2])
            except Exception:
                message = f"平仓股数无效: {args[2]}"
                sender.send_message(message)
                return False, message

        return self.close_contract(xuid, sender, position_id, share_to_close)

    def close_contract(self, xuid, sender, position_id, share_to_close=None,
                       close_price=None, is_liquidation=False):
        '''
            平仓结算（手动/强平共用）
            :param close_price: 强平时传入成交价；手动平仓为 None 则取实时价
            :return: (bool, message)
        '''
        pos = self.stock_dao.get_margin_position(position_id)
        if pos is None or str(pos["player_xuid"]) != str(xuid):
            message = f"仓位 #{position_id} 不存在"
            if not is_liquidation:
                sender.send_message(message)
            return False, message
        if pos["status"] != "open":
            message = f"仓位 #{position_id} 已平仓，无法重复操作"
            if not is_liquidation:
                sender.send_message(message)
            return False, message

        direction_text = "多" if pos["direction"] == "long" else "空"
        stock_name = pos["stock_name"]
        share = int(pos["share"])

        if close_price is None:
            market_price, tradeable = self.get_stock_last_price(stock_name)
            if tradeable is None or market_price is None:
                message = f"无法获取 {stock_name} 的当前价格，请稍后再试"
                if not is_liquidation:
                    sender.send_message(message)
                return False, message
            close_price = market_price
        price = Decimal(str(close_price))

        if share_to_close is None or share_to_close >= share:
            close_share = share
        else:
            close_share = max(1, int(share_to_close))

        interest_hourly = self.setting_manager.get_contract_interest_hourly()
        pnl, interest = self._calc_contract_pnl_interest(pos, price, interest_hourly)

        proportion = Decimal(close_share) / Decimal(share)
        margin_part = Decimal(str(pos["margin"])) * proportion
        open_fee_part = Decimal(str(pos["open_fee"])) * proportion
        pnl_part = pnl * proportion
        interest_part = interest * proportion

        close_value = price * Decimal(close_share)
        fee_rate = Decimal(str(self.setting_manager.get_trading_fee_rate() / 100))
        close_fee = close_value * fee_rate

        returned = margin_part + pnl_part - close_fee - interest_part

        liquidation_fee = Decimal(0)
        if is_liquidation:
            liq_rate = Decimal(str(self.setting_manager.get_contract_liquidation_fee_rate() / 100))
            liquidation_fee = close_value * liq_rate
            returned = max(returned - liquidation_fee, Decimal(0))

        realized_pnl = returned - margin_part - open_fee_part

        self.stock_dao.settle_margin_position(
            position_id, close_share, price, close_fee, interest_part,
            liquidation_fee, realized_pnl,
            "liquidation" if is_liquidation else "manual"
        )
        self.stock_dao.increase_balance(xuid, returned)

        order_type = "contract_liquidation" if is_liquidation else "contract_close"
        order_id = self.stock_dao.create_order(xuid, stock_name, close_share, order_type)
        self.stock_dao.finish_order(order_id, price, close_fee + interest_part, returned)

        if is_liquidation:
            message = (
                f"§c合约 #{position_id}（{stock_name} 开{direction_text} {pos['leverage']}x）已被强制平仓！\n"
                f"§c平仓价 ${float(price):.2f}，净盈亏 {float(realized_pnl):+.2f} 元"
                f"（含强平费 {float(liquidation_fee):.2f}、利息 {float(interest_part):.2f}）\n"
                f"§e返还结算款 {float(returned):.2f} 元至余额"
            )
        else:
            partial_text = f"（部分平仓 {close_share}/{share} 股）" if close_share < share else ""
            message = (
                f"§a合约 #{position_id} 平仓成功！{partial_text}\n"
                f"§e{stock_name} 平仓价 ${float(price):.2f}，净盈亏 {float(realized_pnl):+.2f} 元"
                f"（含平仓费 {float(close_fee):.2f}、利息 {float(interest_part):.2f}）\n"
                f"§e结算款 {float(returned):.2f} 元已返还至余额"
            )
            sender.send_message(message)
        return True, message

    def add_margin_cmd(self, xuid, sender, args):
        '''
            追加保证金 /stock margin <仓位号> <金额>
        '''
        try:
            position_id = int(args[1])
        except Exception:
            message = f"仓位号无效: {args[1] if len(args) > 1 else ''}"
            sender.send_message(message)
            return False, message

        try:
            amount = Decimal(str(float(args[2])))
        except Exception:
            message = f"追加金额无效: {args[2] if len(args) > 2 else ''}"
            sender.send_message(message)
            return False, message

        return self.add_margin(xuid, sender, position_id, amount)

    def add_margin(self, xuid, sender, position_id, amount):
        '''
            从余额向合约仓位追加保证金
            :return: (bool, message)
        '''
        if amount <= 0:
            message = "追加金额必须大于 0"
            sender.send_message(message)
            return False, message

        pos = self.stock_dao.get_margin_position(position_id)
        if pos is None or str(pos["player_xuid"]) != str(xuid):
            message = f"仓位 #{position_id} 不存在"
            sender.send_message(message)
            return False, message
        if pos["status"] != "open":
            message = f"仓位 #{position_id} 已平仓，无需追加"
            sender.send_message(message)
            return False, message

        balance = self.stock_dao.get_balance(xuid)
        if balance is None or Decimal(str(balance)) < amount:
            message = f"余额不足：需 {float(amount):.2f} 元，当前余额 {balance} 元"
            sender.send_message(message)
            return False, message

        interest_hourly = self.setting_manager.get_contract_interest_hourly()
        maintenance_rate = self.setting_manager.get_contract_maintenance_rate()

        # 追加前指标
        market_price, tradeable = self.get_stock_last_price(pos["stock_name"])
        old_liq_text = "获取失败"
        old_rate_text = "获取失败"
        if tradeable and market_price:
            pnl, interest = self._calc_contract_pnl_interest(pos, market_price, interest_hourly)
            old_margin = Decimal(str(pos["margin"]))
            old_equity = old_margin + pnl - interest
            if old_margin > 0:
                old_rate_text = f"{float(old_equity / old_margin * 100):.1f}%"
            old_liq_text = f"${float(self._calc_contract_liquidation_price(pos, maintenance_rate)):.2f}"

        new_margin = Decimal(str(pos["margin"])) + amount
        self.stock_dao.decrease_balance(xuid, amount)
        self.stock_dao.add_margin(position_id, new_margin)

        # 现金流留痕
        order_id = self.stock_dao.create_order(xuid, pos["stock_name"], 0, "contract_add_margin")
        self.stock_dao.finish_order(order_id, 0, 0, amount)

        # 追加后指标
        new_liq_text = "获取失败"
        new_rate_text = "获取失败"
        fresh = self.stock_dao.get_margin_position(position_id)
        if tradeable and market_price and fresh:
            pnl, interest = self._calc_contract_pnl_interest(fresh, market_price, interest_hourly)
            new_equity = new_margin + pnl - interest
            if new_margin > 0:
                new_rate_text = f"{float(new_equity / new_margin * 100):.1f}%"
            new_liq_text = f"${float(self._calc_contract_liquidation_price(fresh, maintenance_rate)):.2f}"

        message = (
            f"§a合约 #{position_id}（{pos['stock_name']} 开{'多' if pos['direction'] == 'long' else '空'} {pos['leverage']}x）"
            f"追加保证金 {float(amount):.2f} 元成功！\n"
            f"§e保证金总额: {float(new_margin):.2f} 元\n"
            f"§e剩余保证金率: {old_rate_text} → §a{new_rate_text}§r\n"
            f"§e预估强平价: {old_liq_text} → §a{new_liq_text}§r\n"
            f"§7借入部分减少，后续利息也会变慢"
        )
        sender.send_message(message)
        return True, message

    def check_contract_positions(self):
        """强平/预警检测任务（调度器回调，网络操作在子线程执行）"""
        def _execute():
            try:
                positions = self.stock_dao.get_open_margin_positions()
                if not positions:
                    return

                interest_hourly = self.setting_manager.get_contract_interest_hourly()
                maintenance_rate = Decimal(str(self.setting_manager.get_contract_maintenance_rate()))
                warning_rate = Decimal(str(self.setting_manager.get_contract_warning_rate()))

                # 价格缓存：60 秒 TTL，控制 yfinance 请求量
                now = time.time()
                price_cache = getattr(self, "_contract_price_cache", None)
                if price_cache is None:
                    price_cache = {}
                    self._contract_price_cache = price_cache

                prices = {}
                for pos in positions:
                    stock = pos["stock_name"]
                    if stock in prices:
                        continue
                    cached = price_cache.get(stock)
                    if cached and now - cached[1] < 60:
                        prices[stock] = cached[0]
                        continue
                    try:
                        fresh_price, _ = self.get_stock_last_price(stock)
                    except Exception:
                        fresh_price = None
                    price_cache[stock] = (fresh_price, now)
                    prices[stock] = fresh_price

                to_liquidate = []
                to_warn = []
                to_clear_warn = []
                for pos in positions:
                    price = prices.get(pos["stock_name"])
                    if not price:
                        continue
                    pnl, interest = self._calc_contract_pnl_interest(pos, price, interest_hourly)
                    margin = Decimal(str(pos["margin"]))
                    equity = margin + pnl - interest
                    if equity <= margin * maintenance_rate / Decimal(100):
                        to_liquidate.append((pos, price))
                    elif equity <= margin * warning_rate / Decimal(100):
                        if not pos["warned"]:
                            to_warn.append((pos, equity, margin))
                    else:
                        if pos["warned"]:
                            to_clear_warn.append(pos)

                for pos in to_clear_warn:
                    try:
                        self.stock_dao.set_margin_warned(pos["id"], 0)
                    except Exception:
                        pass

                for pos, equity, margin in to_warn:
                    try:
                        self.stock_dao.set_margin_warned(pos["id"], 1)
                        player = self._get_online_player_by_xuid(pos["player_xuid"])
                        if player:
                            rate = float(equity / margin * 100)
                            player.send_message(
                                f"§c【合约预警】仓位 #{pos['id']}（{pos['stock_name']} "
                                f"{'多' if pos['direction'] == 'long' else '空'} {pos['leverage']}x）"
                                f"权益仅剩保证金的 {rate:.1f}%，即将触及强平线，请及时平仓或追加保证金！"
                            )
                    except Exception:
                        pass

                for pos, price in to_liquidate:
                    player_lock = self.lock_manager.get_player_lock(str(pos["player_xuid"]))
                    try:
                        with LockWithTimeout(player_lock, 0.2):
                            fresh = self.stock_dao.get_margin_position(pos["id"])
                            if fresh is None or fresh["status"] != "open":
                                continue
                            success, message = self.close_contract(
                                fresh["player_xuid"], None, fresh["id"],
                                close_price=price, is_liquidation=True
                            )
                            if success:
                                self.logger.warning(
                                    f"[UpAndDown] 合约强平 #{pos['id']} 玩家 {pos['player_xuid']}: {message}"
                                )
                                player = self._get_online_player_by_xuid(pos["player_xuid"])
                                if player:
                                    player.send_message(message)
                    except LockException:
                        # 玩家正在交易，下一轮再检测
                        continue
            except Exception as e:
                self.logger.error(f"[UpAndDown] 合约检测任务异常: {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())

        threading.Thread(target=_execute).start()

    def show_positions_cmd(self, xuid, sender, args):
        '''查看未平仓合约 /stock positions [page]'''
        page = 0
        if len(args) > 1:
            try:
                page = max(0, int(args[1]) - 1)
            except Exception:
                page = 0

        positions = self.stock_dao.get_margin_positions(xuid, status='open', page=page, page_size=8)
        if not positions:
            sender.send_message("§e当前没有未平仓合约，使用 /stock long|short 开仓" if page == 0 else "§e本页没有更多仓位")
            return

        interest_hourly = self.setting_manager.get_contract_interest_hourly()
        maintenance_rate = self.setting_manager.get_contract_maintenance_rate()

        price_cache = {}
        total_equity = Decimal(0)
        message = "§g=== 我的合约仓位 ===\n"
        for pos in positions:
            stock = pos["stock_name"]
            if stock not in price_cache:
                try:
                    current_price, _ = self.get_stock_last_price(stock)
                except Exception:
                    current_price = None
                price_cache[stock] = current_price
            price = price_cache[stock]

            direction_text = "多" if pos["direction"] == "long" else "空"
            message += f"\n§g合约#§h{pos['id']} §g{stock} §h{'§a开多' if pos['direction'] == 'long' else '§c开空'}§h {pos['leverage']}x\n"
            message += f"§g股数:§h {pos['share']} §g|开仓价:§h ${float(pos['entry_price']):.2f}"

            if not price:
                message += " §7(价格获取失败)\n"
                continue

            pnl, interest = self._calc_contract_pnl_interest(pos, price, interest_hourly)
            margin = Decimal(str(pos["margin"]))
            equity = margin + pnl - interest
            total_equity += equity
            profit_color = self.plugin_color_for(xuid, pnl)
            liq_price = self._calc_contract_liquidation_price(pos, maintenance_rate)
            rate = float(equity / margin * 100) if margin > 0 else 0

            message += f" §g|现价:§h ${float(price):.2f}\n"
            message += f"§g浮动盈亏:§h {profit_color}{float(pnl):+.2f}§r §g|利息:§h -{float(interest):.2f}\n"
            message += f"§g权益:§h {float(equity):.2f} §g|剩余保证金率:§h {rate:.1f}% §g|强平价≈§h ${float(liq_price):.2f}\n"

        if page == 0:
            message += f"\n§g权益合计:§h {float(total_equity):.2f} 元"
        message += "\n§e使用 /stock close <仓位号> [股数] 平仓，/stock ui 可图形化操作"
        if len(positions) >= 8:
            message += f"\n§e使用 /stock positions {page + 2} 显示下一页"
        sender.send_message(message)

    def plugin_color_for(self, xuid, value):
        """按玩家配色偏好返回涨跌颜色码"""
        try:
            return self.ui_manager.plugin.player_settings_manager.get_color_for_change(xuid, float(value))
        except Exception:
            return "§a" if value >= 0 else "§c"

    def help(self, xuid, sender, args):
        """显示帮助信息 - 使用UI形式"""
        player_name = self._extract_player_name(sender.name)
        player = self.server.get_player(player_name)
        if player and hasattr(player, 'send_form'):
            # 如果玩家在线且有UI支持，显示UI帮助
            self.ui_manager.show_help_panel(player)
        else:
            # 如果无法显示UI，回退到文本消息
            help_str = '''
§c警告：本插件为模拟美股交易插件，您的所有操作均为模拟操作，不会产生真实交易。您只能将股票买卖的利润转为游戏币，您永远无法将其提现为现实中可交易的货币。

§6欢迎来到"荣辱浮沉 (Ups and Downs)" 股票插件，在这里，你可以让自己的财富名列服务器榜首，又或者跟随某个臭名昭著的企业的股票一夜蒸发。

§6这里的一切股票价格都跟实时同步美股市场，所以我强烈推荐你用现实中的股票软件选股和盯盘。股票价格是非常珍贵的数据，我们所提供的数据也仅供参考。

§6如果你不会查股票？那我建议你学起来，毕竟在这里验证你的智商后，你也会迈向亏光家产，哦不，我是说盆满钵满的那一天，你说对吧？

§h指令列表:
/stock ui           §a打开图形化UI界面（推荐使用）
/stock transferin   将资金从服务器经济系统中转入股票账户
/stock transferout  将资金从股票账户中转入服务器经济系统
/stock show <股票代码> [时间范围]   查看股票变化， 时间范围选项: minute (10分钟), day (10天), month (10个月)，默认为minute
/stock account  查看我的股票账户余额
/stock buy <股票代码> <股份数> [价格]   购买股票，份数为整数，不填写价格则为市价单，填写价格则为限价单
/stock sell <股票代码> <股份数> [价格]   出售股票，份数为整数，不填写价格则为市价单，填写价格则为限价单
/stock long <股票代码> <保证金> [杠杆]   合约开多（看涨），可选杠杆倍数见服务器配置，默认最低档
/stock short <股票代码> <保证金> [杠杆]   合约开空（看跌），股价下跌盈利，亏损达保证金90%会被强制平仓
/stock close <仓位号> [股数]   合约平仓，不填股数则全部平仓
/stock margin <仓位号> <金额>   向合约仓位追加保证金，拉远强平价并减少利息
/stock positions [页数]   查看我的未平仓合约，页数默认为1
/stock orders [页数]    查看我的历史订单，页数默认为1
/stock shares [页数]    查看我的持仓，页数默认为1

§h合约交易（做空/杠杆）须知:
§6• 合约为逐仓模式：每笔仓位独立核算，爆仓最多亏掉该笔保证金，不会连累账户余额
§6• 开仓收取手续费，持仓期间按小时对借入部分计息，平仓时结算
§6• 权益跌至保证金维持线（默认10%）将被系统强制平仓并收取强平费
§6• 临近强平可追加保证金自救，也可部分/全部平仓止损
§6• 做空有无限风险：股价上涨理论上无上限，请严格控制杠杆与仓位

/stock help 显示本帮助

§s提示：由于屏幕大小限制，↑↑↑请向上滚动阅读完整内容↑↑↑
        
        '''
            
            sender.send_message(help_str)
        
    def show_orders(self, xuid, sender, args):
        player_name = self._extract_player_name(sender.name)
        player = self.server.get_player(player_name)
        
        if len(args) == 1:
            page = 0
        else:
            page = args[1] - 1
            
        order_list = self.stock_dao.get_orders(xuid, page)
        
        message = ""
        for order in order_list:
            message += f"§g类型:§h {self.order_type_dict[order['type']]}"
            message += f'§g股票名:§h {order["stock_name"]}'
            message += f'§g股数:§h {order["share"]}'
            message += f'§g单价:§h {order["single_price"]}'
            message += f'§g手续费:§h {order["tax"]}'
            message += f'§g总价:§h {order["total"]}'
            
            
            message += "\n"
            
        sender.send_message(message)
        sender.send_message(f"使用/stock orders {page + 2} 显示下一页")
        
    
    def show_shares(self, xuid, sender, args):
        player_name = self._extract_player_name(sender.name)
        player = self.server.get_player(player_name)
        
        if len(args) == 1:
            page = 0
        else:
            page = args[1] - 1
            
        share_list = self.stock_dao.get_shares(xuid, page)
        
        message = ""
        for order in share_list:
            message += f'§g股票名:§h {order["stock_name"]}'
            message += f'§g股数:§h {order["share"]}'
            
            
            message += "\n"
            
        sender.send_message(message)
        sender.send_message(f"使用/stock shares {page + 2} 显示下一页")


    def send_to_qq_group(self, message: str):
        """
        发送消息到QQ群（经弧光 EndStone 消息中枢）。
        优先 api_send_raw（自动加服务器前缀），其次 api_send_message。
        """
        try:
            qqsync = self.qqsync or self._get_qq_sync_plugin()
            if qqsync is None:
                self.logger.warning("[UpAndDown] QQ Sync 插件未找到，无法发送群消息")
                return
            self.qqsync = qqsync

            if hasattr(qqsync, "api_send_raw"):
                success = qqsync.api_send_raw(message)
            elif hasattr(qqsync, "api_send_message"):
                success = qqsync.api_send_message(message)
            else:
                self.logger.warning("[UpAndDown] QQ Sync 无可用发送 API")
                return

            if success:
                self.logger.info(f"[UpAndDown] 群消息已发送: {message[:80]}...")
            else:
                self.logger.warning(f"[UpAndDown] 群消息发送失败: {message[:80]}...")
        except Exception as e:
            self.logger.error(f"[UpAndDown] 群消息发送异常: {str(e)}")
            # 即使 QQ 群发送失败，也不影响游戏正常运行


    def update_leaderboard(self):
        def _execute():
            """Update leaderboard data for both absolute and relative profit/loss"""
            try:
                self.logger.info("Leaderboard updating")

                try:
                    # Call get_all_players_profit_loss with is_absolute=True
                    interest_hourly = self.setting_manager.get_contract_interest_hourly()
                    absolute_data = self.stock_dao.get_all_players_profit_loss(self.get_stock_last_price, interest_hourly)
                    self.stock_dao.save_leaderboard_data(absolute_data, True)

                    # Call get_all_players_profit_loss with is_absolute=False
                    relative_data = self.stock_dao.get_all_players_profit_loss(self.get_stock_last_price, interest_hourly)
                    self.stock_dao.save_leaderboard_data(relative_data, False)

                    self.logger.info("Leaderboard updated successfully")
                except Exception as e:
                    # 行情拉取失败时仍尝试用缓存发日报，避免整天停发
                    self.logger.error(f"Failed to refresh leaderboard data: {str(e)}")
                    import traceback
                    self.logger.error(traceback.format_exc())

                self._try_send_daily_qq_report()

            except Exception as e:
                self.logger.error(f"Failed to update leaderboard: {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())

        threading.Thread(target=_execute).start()

    def _try_send_daily_qq_report(self):
        """每天 8:00 后首次排行榜任务触发时，向 QQ 群发送相对盈亏日报（每日一次）。"""
        if datetime.datetime.now().time() <= datetime.time(8, 0):
            return

        qqsync = self._get_qq_sync_plugin()
        self.qqsync = qqsync
        if qqsync is None:
            self.logger.warning(
                "[UpAndDown] 未找到 QQ Sync（arc_qq_sync_astrbot），跳过今日股票群日报"
            )
            return

        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        # 先占位防并发重复；发送失败则删掉以便本轮后续任务重试
        if not self.stock_dao.insert_qq_send_log(today_str):
            return

        stored_data = self.get_leaderboard_data(is_absolute=False) or []
        last_updated = stored_data[0]["last_updated"] if stored_data else time.time()

        content = "早安，各位彼阳群友☀️，以下是今日服务器股票排行榜"
        content += (
            f"相对盈亏排行榜 (更新时间: "
            f"{datetime.datetime.fromtimestamp(last_updated).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        content += "前5名 (高手榜)\n\n"

        top5 = stored_data[:5]
        for data in top5:
            player_name = self.ui_manager._get_player_name(data["player_xuid"])
            profit_loss_percent = data["relative_profit_loss"]
            profit_loss = data["absolute_profit_loss"]
            rank = data.get("rank", "?")

            if profit_loss_percent > 0:
                sign = "🟥+"
            elif profit_loss_percent < 0:
                sign = "🟩-"
            else:
                sign = ""

            content += f"#{rank} {player_name}\n"
            content += f"   收益率: {sign}{abs(profit_loss_percent):.2f}%\n"
            content += f"   盈亏: {sign}${abs(profit_loss):.2f}\n\n"

        bottom5 = []
        if len(stored_data) > 5:
            top_xuids = {d["player_xuid"] for d in top5}
            bottom5 = [
                d for d in stored_data[-5:]
                if d["player_xuid"] not in top_xuids
            ]
            bottom5.reverse()

        if bottom5:
            content += "倒数5名 (接盘侠榜)\n\n"
            for data in bottom5:
                player_name = self.ui_manager._get_player_name(data["player_xuid"])
                profit_loss_percent = data["relative_profit_loss"]
                profit_loss = data["absolute_profit_loss"]
                rank = data.get("rank", "?")

                if profit_loss_percent > 0:
                    sign = "🟥+"
                elif profit_loss_percent < 0:
                    sign = "🟩-"
                else:
                    sign = ""

                content += f"#{rank} {player_name}\n"
                content += f"   收益率: {sign}{abs(profit_loss_percent):.2f}%\n"
                content += f"   盈亏: {sign}${abs(profit_loss):.2f}\n\n"
        content += "ARC股票插件，为群友带来初升飞舞的财富🤑"

        try:
            success = False
            if hasattr(qqsync, "api_send_raw"):
                success = bool(qqsync.api_send_raw(content))
            elif hasattr(qqsync, "api_send_message"):
                success = bool(qqsync.api_send_message(content))
            else:
                self.logger.warning("[UpAndDown] QQ Sync 无可用发送 API")

            if success:
                self.logger.info(f"[UpAndDown] 股票群日报已发送: {content[:80]}...")
            else:
                self.stock_dao.delete_qq_send_log(today_str)
                self.logger.warning("[UpAndDown] 股票群日报发送失败，已清除当日标记以便重试")
        except Exception as e:
            self.stock_dao.delete_qq_send_log(today_str)
            self.logger.error(f"[UpAndDown] 股票群日报发送异常: {e}")


    def get_leaderboard_data(self, is_absolute=True):
        """Get leaderboard data from database
        Args:
            is_absolute: True for absolute leaderboard, False for relative
        Returns:
            List of player data or empty list
        """
        try:
            cached_data = self.stock_dao.get_leaderboard_cached_data(is_absolute)
            if len(cached_data) > 0:
                return cached_data
            return []
        except Exception as e:
            self.logger.error(f"Failed to get leaderboard data: {str(e)}")
            return []

    def _resolve_player_display_name(self, player_xuid: str) -> str:
        """Resolve XUID to display name via arc_core when available."""
        try:
            if self.ui_manager is not None:
                return self.ui_manager._get_player_name(player_xuid)
        except Exception:
            pass
        try:
            arc_core = self.server.plugin_manager.get_plugin("arc_core")
            if arc_core is not None:
                name = arc_core.get_player_name_by_xuid(player_xuid)
                if name:
                    return str(name)
        except Exception:
            pass
        return f"玩家{str(player_xuid)[:8]}"

    def api_get_leaderboard_text(
        self,
        mode: str = "relative",
        top: int = 5,
        bottom: int = 5,
        player_name: str = "",
    ) -> str:
        """
        AI / 外部插件：格式化股票盈亏排行榜文本。

        :param mode: relative（收益率）或 absolute（绝对盈亏）
        :param top: 前 N 名
        :param bottom: 倒数 N 名
        :param player_name: 可选；仅查询该玩家名次与盈亏
        """
        is_absolute = str(mode or "relative").strip().lower() in (
            "absolute", "abs", "money", "绝对", "金额"
        )
        try:
            top_n = max(0, min(20, int(top)))
        except Exception:
            top_n = 5
        try:
            bottom_n = max(0, min(20, int(bottom)))
        except Exception:
            bottom_n = 5

        stored = self.get_leaderboard_data(is_absolute=is_absolute) or []
        if not stored:
            return "暂无股票排行榜数据（尚无玩家交易，或排行榜尚未刷新）。"

        title = "绝对盈亏排行榜" if is_absolute else "相对盈亏（收益率）排行榜"
        last_updated = stored[0].get("last_updated") if stored else None
        try:
            updated_str = datetime.datetime.fromtimestamp(float(last_updated)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception:
            updated_str = "未知"

        focus = str(player_name or "").strip()
        if focus:
            focus_lower = focus.lower()
            for data in stored:
                name = self._resolve_player_display_name(data.get("player_xuid") or "")
                if name.lower() != focus_lower and focus_lower not in name.lower():
                    continue
                rank = data.get("rank", "?")
                abs_pl = float(data.get("absolute_profit_loss") or 0)
                rel_pl = float(data.get("relative_profit_loss") or 0)
                sign_abs = "+" if abs_pl > 0 else ("-" if abs_pl < 0 else "")
                sign_rel = "+" if rel_pl > 0 else ("-" if rel_pl < 0 else "")
                return (
                    f"{title}（更新: {updated_str}）\n"
                    f"玩家 {name}：第 {rank} 名\n"
                    f"绝对盈亏: {sign_abs}${abs(abs_pl):.2f}\n"
                    f"收益率: {sign_rel}{abs(rel_pl):.2f}%"
                )
            return f"排行榜中未找到玩家「{focus}」（可能尚未激活股票账户或无成交）。"

        lines = [f"{title}（更新: {updated_str}）", ""]
        if top_n > 0:
            lines.append(f"前{top_n}名：")
            for data in stored[:top_n]:
                name = self._resolve_player_display_name(data.get("player_xuid") or "")
                rank = data.get("rank", "?")
                abs_pl = float(data.get("absolute_profit_loss") or 0)
                rel_pl = float(data.get("relative_profit_loss") or 0)
                if is_absolute:
                    sign = "+" if abs_pl > 0 else ("-" if abs_pl < 0 else "")
                    lines.append(f"#{rank} {name}  盈亏 {sign}${abs(abs_pl):.2f}")
                else:
                    sign = "+" if rel_pl > 0 else ("-" if rel_pl < 0 else "")
                    lines.append(
                        f"#{rank} {name}  收益率 {sign}{abs(rel_pl):.2f}%  "
                        f"(${abs(abs_pl):.2f})"
                    )
            lines.append("")

        if bottom_n > 0 and len(stored) > top_n:
            lines.append(f"倒数{bottom_n}名：")
            top_xuids = {
                d.get("player_xuid") for d in stored[:top_n] if d.get("player_xuid")
            }
            bottom_rows = [
                d for d in stored[-bottom_n:]
                if d.get("player_xuid") not in top_xuids
            ]
            bottom_rows.reverse()
            for data in bottom_rows:
                name = self._resolve_player_display_name(data.get("player_xuid") or "")
                rank = data.get("rank", "?")
                abs_pl = float(data.get("absolute_profit_loss") or 0)
                rel_pl = float(data.get("relative_profit_loss") or 0)
                if is_absolute:
                    sign = "+" if abs_pl > 0 else ("-" if abs_pl < 0 else "")
                    lines.append(f"#{rank} {name}  盈亏 {sign}${abs(abs_pl):.2f}")
                else:
                    sign = "+" if rel_pl > 0 else ("-" if rel_pl < 0 else "")
                    lines.append(
                        f"#{rank} {name}  收益率 {sign}{abs(rel_pl):.2f}%  "
                        f"(${abs(abs_pl):.2f})"
                    )

        lines.append("")
        lines.append("说明：模拟美股交易盈亏，仅供娱乐，不构成投资建议。")
        return "\n".join(lines)

    def api_get_stock_quote_text(self, symbol: str, period: str = "day") -> str:
        """
        AI / 外部插件：查询单个股票现价与走势摘要。

        :param symbol: 股票代码，如 AAPL / TSLA / BTC-USD
        :param period: price（仅现价）| minute | day | month
        """
        stock = str(symbol or "").strip().upper()
        if not stock:
            return "股票代码为空"
        unit = str(period or "day").strip().lower() or "day"
        if unit in ("price", "now", "current", "现价", "最新"):
            price, tradeable = self.get_stock_last_price(stock)
            if price is None:
                return f"无法获取 {stock} 的价格（代码错误或该市场暂不支持）。"
            return (
                f"{stock} 最新价: ${float(price):.2f}\n"
                f"可交易: {'是' if tradeable else '否'}\n"
                "以上为 yfinance 参考价，仅供服务器模拟交易使用。"
            )

        if unit in ("minute", "min", "10m", "分钟"):
            price_list, _ = self.get_stock_last_price(stock, return_period=True)
            unit_zh = "近10分钟（1分钟K）"
        elif unit in ("month", "mo", "1y", "月"):
            price_list, _ = self.get_stock_last_price(
                stock, period="1y", interval="1mo", return_period=True
            )
            unit_zh = "近10个月（月线）"
        else:
            price_list, _ = self.get_stock_last_price(
                stock, period="1mo", interval="1d", return_period=True
            )
            unit_zh = "近10天（日线）"

        if not price_list:
            return f"无法获取 {stock} 的走势（代码错误或该市场暂不支持）。"

        series = [round(float(p), 2) for p in price_list[-11:]]
        if len(series) < 2:
            return f"{stock} 数据不足，暂无法展示走势。"

        latest = series[-1]
        first = series[0]
        change = latest - first
        change_pct = (change / first * 100) if first else 0.0
        sign = "+" if change > 0 else ""
        points = []
        for idx, price in enumerate(series):
            if idx == 0:
                points.append(f"{price}")
                continue
            prev = series[idx - 1]
            mark = "↑" if price > prev else ("↓" if price < prev else "→")
            points.append(f"{mark}{price}")

        return (
            f"{stock} {unit_zh}走势\n"
            f"最新: ${latest:.2f}  区间变动: {sign}{change:.2f} ({sign}{change_pct:.2f}%)\n"
            f"序列: {' '.join(points)}\n"
            "以上数据仅供参考，建议使用专业行情软件核对。"
        )

    @event_handler
    def on_server_load(self, event: ServerLoadEvent):
        self.logger.info(f"{event.event_name} is passed to on_server_load")

    @event_handler(priority=EventPriority.HIGH)
    def on_server_load_2(self, event: ServerLoadEvent):
        # this will be called after on_server_load because of a higher priority
        self.logger.info(f"{event.event_name} is passed to on_server_load2")

    def log_time(self):
        now = datetime.datetime.now().strftime("%c")
        for player in self.server.online_players:
            player.send_popup(now)
