import time
from decimal import *

from endstone_up_and_down.databaseManager import DatabaseManager

class StockDao:
    def __init__(self, database_manager):
        self.database_manager:DatabaseManager = database_manager
        
        
    def init_tables(self) -> bool:
        """Player Share Table"""
        self.database_manager.create_table("tb_player_stock", {
            "id": "INTEGER primary key autoincrement",
            "player_xuid": "TEXT",
            "stock_name": "nvarchar",
            "share": "int",
            "time": "float"
        })

        '''Player order table'''
        self.database_manager.create_table("tb_player_order", {
            "id": "INTEGER primary key autoincrement",
            "player_xuid": "TEXT",
            "stock_name": "nvarchar",
            "share": "int",
            "single_price": "float",
            "type": "nvarchar",
            "create_time": "float",
            "finish_time": "float",
            "tax": "float",
            "total": "float"
        })
        
        '''Player account table'''
        self.database_manager.create_table("tb_player_account",{
            "player_xuid": "TEXT",
            "balance": "float"
        })
            
        # Leaderboard table
        self.database_manager.create_table("tb_leaderboard", {
            "id": "INTEGER primary key autoincrement",
            "player_xuid": "TEXT",
            "total_wealth": "float",
            "holdings_value": "float",
            "balance": "float",
            "total_buy": "float",
            "total_sell": "float",
            "absolute_profit_loss": "float",
            "relative_profit_loss": "float",
            "is_absolute": "BOOLEAN",
            "last_updated": "float",
            "rank": "int"
        })

        """QQ Notice record Table"""
        self.database_manager.create_table("tb_qq_notice", {
            "id": "INTEGER primary key autoincrement",
            "send_date": "TEXT"
        })

        '''Contract (margin) position table 逐仓合约仓位表'''
        self.database_manager.create_table("tb_margin_position", {
            "id": "INTEGER primary key autoincrement",
            "player_xuid": "TEXT",
            "stock_name": "nvarchar",
            "direction": "nvarchar",      # long / short
            "leverage": "int",
            "margin": "float",            # 保证金
            "share": "int",
            "entry_price": "float",
            "open_time": "float",
            "open_fee": "float",
            "status": "nvarchar",         # open / closed / liquidated
            "close_price": "float",
            "close_time": "float",
            "close_fee": "float",
            "interest": "float",
            "liquidation_fee": "float",
            "realized_pnl": "float",      # 平仓净盈亏（含开仓费分摊/平仓费/利息/强平费）
            "close_reason": "nvarchar",   # manual / liquidation
            "warned": "int"
        })
        
        
    def create_order(self, xuid, stock_name, share, type):
        stock_name = stock_name.upper()
        
        self.database_manager.insert("tb_player_order", {
            "player_xuid": xuid,
            "stock_name": stock_name,
            "share": share,
            "type": type,
            "create_time": time.time(),
        })

        result = self.database_manager.query_one(
            "SELECT id FROM tb_player_order WHERE player_xuid = ? ORDER BY id DESC LIMIT 1",
            (xuid,)
        )
        order_id = result["id"] if result else None
        
        return order_id

    def finish_order(self, order_id, price, tax, total):
        """合约订单完结：回填成交价/费用/现金流"""
        self.database_manager.update("tb_player_order", {
            "single_price": float(price),
            "finish_time": time.time(),
            "tax": float(tax),
            "total": float(total)
        }, f"id = {order_id}")

    def buy(self, order_id, stock_name, xuid, share, price, tax, total):
        stock_name = stock_name.upper()
        
        # Buy
        exists_share = self.database_manager.query_one("SELECT * FROM tb_player_stock WHERE player_xuid = ? AND stock_name = ?", (xuid, stock_name))
        if exists_share == None:
            self.database_manager.insert("tb_player_stock", {
                "player_xuid": xuid,
                "stock_name": stock_name,
                "share": share,
                "time": time.time()
            })
        else:
            new_share = exists_share["share"] + share
            id = exists_share["id"]
            
            self.database_manager.update("tb_player_stock",{
                "share": new_share
            }, f"id = {id}")

        self.database_manager.update("tb_player_order", {
            "single_price": price,
            "finish_time": time.time(),
            "tax": tax,
            "total": total
        }, f"id = {order_id}")
        
        
    def sell(self, order_id, stock_name, xuid, share, price, tax, total):
        stock_name = stock_name.upper()
        
        # Sell stock
        # 查询玩家当前持股记录
        exists_share = self.database_manager.query_one(
            "SELECT * FROM tb_player_stock WHERE player_xuid = ? AND stock_name = ?", 
            (xuid, stock_name)
        )
        
        if exists_share is None:
            # 理论上不会发生，因为调用前已检查持股
            raise ValueError(f"Player {xuid} has no stock {stock_name} to sell")
        
        current_share = exists_share["share"]
        record_id = exists_share["id"]
        
        # 计算卖出后的持股数量
        new_share = current_share - share
        
        # 更新持股数量
        self.database_manager.update(
            "tb_player_stock",
            {"share": new_share},
            f"id = {record_id}"
        )
        
        # 更新订单状态
        self.database_manager.update(
            "tb_player_order",
            {
                "single_price": price,
                "finish_time": time.time(),
                "tax": tax,
                "total": total
            },
            f"id = {order_id}"
        )
        
    def check_user_account(self, xuid):
        user_count = self.database_manager.query_one('SELECT COUNT(*) as count FROM tb_player_account WHERE player_xuid = ? ', (xuid,))
        return user_count["count"] == 1

    # ==================== 合约（逐仓杠杆/做空）仓位 ====================

    def create_margin_position(self, xuid, stock_name, direction, leverage, margin, share, entry_price, open_fee):
        """创建合约仓位，返回仓位ID"""
        stock_name = stock_name.upper()
        self.database_manager.insert("tb_margin_position", {
            "player_xuid": xuid,
            "stock_name": stock_name,
            "direction": direction,
            "leverage": leverage,
            "margin": float(margin),
            "share": int(share),
            "entry_price": float(entry_price),
            "open_time": time.time(),
            "open_fee": float(open_fee),
            "status": "open",
            "warned": 0
        })
        result = self.database_manager.query_one(
            "SELECT id FROM tb_margin_position WHERE player_xuid = ? ORDER BY id DESC LIMIT 1",
            (xuid,)
        )
        return result["id"] if result else None

    def get_margin_position(self, position_id):
        return self.database_manager.query_one(
            "SELECT * FROM tb_margin_position WHERE id = ?", (position_id,)
        )

    def get_open_margin_positions(self, xuid=None):
        """查询未平仓仓位；xuid 为 None 时返回全服（供强平引擎使用）"""
        if xuid is None:
            return self.database_manager.query_all(
                "SELECT * FROM tb_margin_position WHERE status = 'open' ORDER BY id ASC"
            )
        return self.database_manager.query_all(
            "SELECT * FROM tb_margin_position WHERE status = 'open' AND player_xuid = ? ORDER BY id DESC",
            (xuid,)
        )

    def get_margin_positions(self, player_xuid, status=None, page=1, page_size=10, exclude_open=False):
        """
        分页查询玩家合约仓位
        :param status: 指定状态精确过滤（open/closed/liquidated）
        :param exclude_open: True 时查所有已平仓（closed+liquidated）
        """
        offset = (page - 1) * page_size
        sql = "SELECT * FROM tb_margin_position WHERE player_xuid = ?"
        params = [player_xuid]
        if exclude_open:
            sql += " AND status != 'open'"
        elif status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])
        return self.database_manager.query_all(sql, tuple(params))

    def get_open_margin_summary(self, xuid):
        """主面板用：未平仓笔数与占用保证金合计（不拉价格）"""
        row = self.database_manager.query_one(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(margin), 0) AS total FROM tb_margin_position WHERE player_xuid = ? AND status = 'open'",
            (xuid,)
        )
        if not row:
            return 0, 0.0
        return int(row["cnt"] or 0), float(row["total"] or 0.0)

    def get_closed_margin_pnl_total(self, xuid):
        """已平仓（含强平）净盈亏合计"""
        row = self.database_manager.query_one(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM tb_margin_position WHERE player_xuid = ? AND status != 'open'",
            (xuid,)
        )
        return float(row["total"]) if row and row["total"] is not None else 0.0

    def get_margin_deployed_total(self, xuid):
        """历史累计投入合约的资金（保证金+开仓费），供相对盈亏做分母"""
        row = self.database_manager.query_one(
            "SELECT COALESCE(SUM(margin + open_fee), 0) AS total FROM tb_margin_position WHERE player_xuid = ?",
            (xuid,)
        )
        return float(row["total"]) if row and row["total"] is not None else 0.0

    def set_margin_warned(self, position_id, warned):
        self.database_manager.update(
            "tb_margin_position", {"warned": 1 if warned else 0}, f"id = {position_id}"
        )

    def add_margin(self, position_id, new_margin):
        """追加保证金：直接写入追加后的保证金总额（调用方持玩家锁，无竞态）"""
        self.database_manager.update(
            "tb_margin_position",
            {"margin": float(new_margin), "warned": 0},
            f"id = {position_id}"
        )

    def settle_margin_position(self, position_id, close_share, close_price, close_fee,
                               interest, liquidation_fee, realized_pnl, close_reason):
        """
        平仓结算：close_share 达到持仓股数时整行置为已平仓；
        部分平仓时原行按比例缩减 share/margin/open_fee，平掉部分另插一行已平仓记录。
        :return: (position_row_after, closed_row) 或 (None, None) 表示仓位不存在或已平
        """
        pos = self.get_margin_position(position_id)
        if pos is None or pos["status"] != "open":
            return None, None

        share = int(pos["share"])
        close_share = max(1, min(int(close_share), share))
        proportion = Decimal(str(close_share)) / Decimal(str(share))

        closed_margin = float(Decimal(str(pos["margin"])) * proportion)
        closed_open_fee = float(Decimal(str(pos["open_fee"])) * proportion)
        status = "liquidated" if close_reason == "liquidation" else "closed"

        closed_fields = {
            "stock_name": pos["stock_name"],
            "player_xuid": pos["player_xuid"],
            "direction": pos["direction"],
            "leverage": pos["leverage"],
            "margin": closed_margin,
            "share": close_share,
            "entry_price": pos["entry_price"],
            "open_time": pos["open_time"],
            "open_fee": closed_open_fee,
            "status": status,
            "close_price": float(close_price),
            "close_time": time.time(),
            "close_fee": float(close_fee),
            "interest": float(interest),
            "liquidation_fee": float(liquidation_fee),
            "realized_pnl": float(realized_pnl),
            "close_reason": close_reason,
            "warned": pos["warned"] or 0,
        }

        if close_share >= share:
            self.database_manager.update("tb_margin_position", closed_fields, f"id = {position_id}")
            closed_fields["id"] = position_id
            return None, closed_fields

        # 部分平仓：缩减原行，另插已平行
        remain_margin = float(Decimal(str(pos["margin"])) - Decimal(str(closed_margin)))
        remain_open_fee = float(Decimal(str(pos["open_fee"])) - Decimal(str(closed_open_fee)))
        self.database_manager.update("tb_margin_position", {
            "share": share - close_share,
            "margin": remain_margin,
            "open_fee": remain_open_fee,
        }, f"id = {position_id}")

        closed_fields.pop("id", None)
        self.database_manager.insert("tb_margin_position", closed_fields)

        remain = self.get_margin_position(position_id)
        return remain, closed_fields

    def get_balance(self, xuid):
        account = self.database_manager.query_one("SELECT * FROM tb_player_account WHERE player_xuid = ? ", (xuid,))

        if account == None or account["balance"] == None:
            return None
        return account["balance"]
        
        
    def increase_balance(self, xuid, amount, is_transfer_in=False):
        """
        增加余额
        :param xuid: 玩家XUID
        :param amount: 金额
        :param is_transfer_in: 是否为转入操作（影响累计投入）
        """
        account = self.database_manager.query_one("SELECT * FROM tb_player_account WHERE player_xuid = ? ", (xuid,))
        
        if account == None:
            # 新账户
            self.database_manager.insert("tb_player_account", {
                "player_xuid": xuid,
                "balance": amount
            })
        else:
            new_balance = float(Decimal(str(account["balance"])) + Decimal(str(amount)))
            self.database_manager.update("tb_player_account", {
                "balance": new_balance
            }, f"player_xuid='{xuid}'")


    def decrease_balance(self, xuid, amount, is_transfer_out=False):
        """
        减少余额
        :param xuid: 玩家XUID
        :param amount: 金额
        :param is_transfer_out: 是否为转出操作（影响累计投入）
        """
        account = self.database_manager.query_one("SELECT * FROM tb_player_account WHERE player_xuid = ? ", (xuid,))
        if account is None:
            raise Exception("User not found")
        else:
            new_balance = float(Decimal(str(account["balance"])) - Decimal(str(amount)))
            self.database_manager.update("tb_player_account", {
                "balance": new_balance
            }, f"player_xuid='{xuid}'")
            
            
    def get_player_stock_holding(self, xuid, stock_name):
        stock_name = stock_name.upper()
        
        exists_share = self.database_manager.query_one(
            "SELECT * FROM tb_player_stock WHERE player_xuid = ? AND stock_name = ?", 
            (xuid, stock_name)
        )
        
        if exists_share == None:
            return 0
        
        return exists_share["share"]
    
    
    def get_orders(self, player_xuid, page=1, page_size=10):
        """
        分页查询玩家订单
        :param player_xuid: 玩家XUID
        :param page: 页码，从1开始
        :param page_size: 每页数量
        :return: 订单列表
        """
        offset = (page - 1) * page_size
        sql =  "SELECT * FROM tb_player_order WHERE player_xuid = ? AND total IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?"
        return self.database_manager.query_all(sql, (player_xuid, page_size, offset))
    
    
    def get_shares(self, player_xuid, page=1, page_size=10):
        offset = (page - 1) * page_size
        sql =  "SELECT * FROM tb_player_stock WHERE player_xuid = ? AND share > 0 ORDER BY id DESC LIMIT ? OFFSET ?"
        return self.database_manager.query_all(sql, (player_xuid, page_size, offset))
    
    
    def get_average_cost(self, player_xuid, stock_name):
        """
        计算玩家持有某股票的平均成本
        :param player_xuid: 玩家XUID
        :param stock_name: 股票名称
        :return: 平均成本价格，如果没有持仓返回None
        """
        # 查询所有买入订单
        buy_orders = self.database_manager.query_all(
            """
            SELECT share, single_price, total 
            FROM tb_player_order 
            WHERE player_xuid = ? 
            AND stock_name = ? 
            AND (type = 'buy_flex' OR type = 'buy_fix')
            AND total IS NOT NULL
            ORDER BY finish_time ASC
            """,
            (player_xuid, stock_name)
        )
        
        # 查询所有卖出订单
        sell_orders = self.database_manager.query_all(
            """
            SELECT share 
            FROM tb_player_order 
            WHERE player_xuid = ? 
            AND stock_name = ? 
            AND (type = 'sell_flex' OR type = 'sell_fix')
            AND total IS NOT NULL
            ORDER BY finish_time ASC
            """,
            (player_xuid, stock_name)
        )
        
        if not buy_orders:
            return None
        
        # 计算总买入成本和总买入股数
        total_cost = Decimal('0')
        total_buy_shares = Decimal('0')
        
        for order in buy_orders:
            share = Decimal(str(order['share']))
            # 总成本包含手续费
            cost = Decimal(str(order['total']))
            total_cost += cost
            total_buy_shares += share
        
        # 计算总卖出股数
        total_sell_shares = Decimal('0')
        for order in sell_orders:
            total_sell_shares += Decimal(str(order['share']))
        
        # 当前持有股数
        current_shares = total_buy_shares - total_sell_shares
        
        if current_shares <= 0:
            return None
        
        # 按比例计算剩余持仓的成本
        # 假设先进先出（FIFO），按比例分摊成本
        remaining_cost = total_cost * (current_shares / total_buy_shares)
        average_cost = remaining_cost / current_shares
        
        return float(average_cost)
    

    def get_leaderboard_cached_data(self, is_absolute):
        # Get current timestamp
        current_time = time.time()
        
        # 返回全量排名（前 N / 倒数 N 都依赖完整榜单；勿 LIMIT 10）
        cached_data = self.database_manager.query_all(
            "SELECT * FROM tb_leaderboard WHERE is_absolute = ? AND last_updated > ? ORDER BY rank",
            (is_absolute, current_time - 3600)
        )

        return cached_data
    
    
    def get_all_players_profit_loss(self, get_stock_price_func, contract_interest_hourly=0.0):
        """
        获取所有玩家的盈亏数据（含现货与逐仓合约）
        :param get_stock_price_func: 获取股票价格的函数
        :param contract_interest_hourly: 合约资金利息（百分比/小时，按借入部分计息）
        :return: 包含玩家盈亏信息的列表
        """
        # 获取所有有账户的玩家
        all_accounts = self.database_manager.query_all(
            "SELECT player_xuid, balance FROM tb_player_account"
        )
        
        if not all_accounts:
            return []
        
        players_data = []

        price_cache_dict = {}
        
        for account in all_accounts:
            player_xuid = account['player_xuid']
            balance = Decimal(str(account['balance']))
            
            # 实时计算累计投入：通过查询买入订单的总成本
            buy_orders = self.database_manager.query_all(
                """
                SELECT share, single_price, tax 
                FROM tb_player_order 
                WHERE player_xuid = ? 
                AND (type = 'buy_flex' OR type = 'buy_fix')
                AND total IS NOT NULL
                """,
                (player_xuid,)
            )

            sell_orders = self.database_manager.query_all(
                """
                SELECT share, single_price, tax 
                FROM tb_player_order 
                WHERE player_xuid = ? 
                AND (type = 'sell_flex' OR type = 'sell_fix')
                AND total IS NOT NULL
                """,
                (player_xuid,)
            )
            
            total_buy = Decimal('0')
            for order in buy_orders:
                # 累计买入 = 买入总金额 + 手续费
                share = Decimal(str(order['share']))
                price = Decimal(str(order['single_price']))
                tax = Decimal(str(order['tax'])) if order['tax'] else Decimal('0')
                total_buy += (share * price) + tax

            total_sell = Decimal('0')
            for order in sell_orders:
                # 累计卖出 = 买入总金额 + 手续费
                share = Decimal(str(order['share']))
                price = Decimal(str(order['single_price']))
                tax = Decimal(str(order['tax'])) if order['tax'] else Decimal('0')
                total_sell += (share * price) + tax
            
            # 如果现货与合约都没有实际投入，跳过（没有实际投资过）
            margin_deployed = Decimal(str(self.get_margin_deployed_total(player_xuid)))
            if total_buy == 0 and margin_deployed == 0:
                continue

            # 计算持仓市值
            holdings_value = Decimal('0')
            holdings = self.database_manager.query_all(
                "SELECT stock_name, share FROM tb_player_stock WHERE player_xuid = ? AND share > 0",
                (player_xuid,)
            )

            for holding in holdings:
                stock_name = holding['stock_name']
                share = Decimal(str(holding['share']))

                # 获取当前股票价格
                if stock_name not in price_cache_dict:
                    try:
                        current_price, _ = get_stock_price_func(stock_name)
                    except Exception:
                        current_price = None
                    price_cache_dict[stock_name] = current_price
                else:
                    current_price = price_cache_dict[stock_name]
                if current_price:
                    holdings_value += current_price * share

            # ===== 合约（逐仓）仓位 =====
            # 已平仓净盈亏直接累加；未平仓按现价算浮动盈亏并扣应计利息
            contract_closed_pl = Decimal(str(self.get_closed_margin_pnl_total(player_xuid)))

            margin_locked = Decimal('0')          # 占用保证金（计入总财富）
            contract_unrealized = Decimal('0')    # 浮动盈亏-应计利息（计入总财富与盈亏）
            contract_open_fee_total = Decimal('0')  # 未平仓开仓费（已从余额扣，计入盈亏）

            open_positions = self.database_manager.query_all(
                "SELECT * FROM tb_margin_position WHERE player_xuid = ? AND status = 'open'",
                (player_xuid,)
            )
            for pos in open_positions:
                stock_name = pos['stock_name']
                if stock_name not in price_cache_dict:
                    try:
                        current_price, _ = get_stock_price_func(stock_name)
                    except Exception:
                        current_price = None
                    price_cache_dict[stock_name] = current_price
                else:
                    current_price = price_cache_dict[stock_name]
                if not current_price:
                    continue

                price = Decimal(str(current_price))
                entry = Decimal(str(pos['entry_price']))
                pos_share = Decimal(str(pos['share']))
                pos_margin = Decimal(str(pos['margin']))
                pnl = (price - entry) * pos_share if pos['direction'] == 'long' else (entry - price) * pos_share
                borrowed = max(entry * pos_share - pos_margin, Decimal('0'))
                hours = Decimal(str(max(time.time() - float(pos['open_time']), 0.0) / 3600.0))
                interest = borrowed * Decimal(str(contract_interest_hourly)) / Decimal('100') * hours

                margin_locked += pos_margin
                contract_unrealized += pnl - interest
                contract_open_fee_total += Decimal(str(pos['open_fee']))

            # 当前盈利 = 持仓市值 - 现货购买成本 + 现货出售收入 + 合约已平净盈亏 + 合约浮动盈亏 - 未平仓开仓费
            absolute_profit_loss = holdings_value - total_buy + total_sell \
                + contract_closed_pl + contract_unrealized - contract_open_fee_total

            # 相对盈亏（百分比） = 绝对盈亏 / 累计投入（现货买入 + 合约保证金与开仓费） * 100
            total_invested = total_buy + margin_deployed
            if total_invested > 0:
                relative_profit_loss = float((absolute_profit_loss / total_invested) * 100)
            else:
                relative_profit_loss = 0.0

            players_data.append({
                'player_xuid': player_xuid,
                'total_wealth': float(holdings_value) + float(balance) + float(margin_locked) + float(contract_unrealized),
                'holdings_value': float(holdings_value),
                'balance': float(balance),
                'total_buy': float(total_invested),
                'total_sell': float(total_sell),
                'absolute_profit_loss': float(absolute_profit_loss),
                'relative_profit_loss': relative_profit_loss
            })
        
        return players_data
    

    def get_cached_single_player_profit_loss(self, player_xuid):
        current_time = time.time()        
        cached_data = self.database_manager.query_one(
            "SELECT * FROM tb_leaderboard WHERE is_absolute = ? AND last_updated > ? AND player_xuid = ? ORDER BY rank LIMIT 10",
            (True, current_time - 3600, player_xuid), 
        )

        if cached_data == None:
            return None

        return {
            'player_xuid': player_xuid,
            'total_wealth': cached_data["total_wealth"],
            'holdings_value': cached_data["holdings_value"],
            'balance': cached_data["balance"],
            'total_buy': cached_data["total_buy"],
            'total_sell': cached_data["total_sell"],
            'absolute_profit_loss': cached_data["absolute_profit_loss"],
            'relative_profit_loss': cached_data["relative_profit_loss"]
        }


    def save_leaderboard_data(self, players_data, is_absolute):
        """
        保存排行榜数据到数据库
        :param players_data: 玩家数据列表
        :param is_absolute: 是否为绝对盈亏排行榜
        """
        # 先清空旧数据
        self.database_manager.execute(
            "DELETE FROM tb_leaderboard WHERE is_absolute = ?", 
            (is_absolute,)
        )
        
        # 按指定字段排序（绝对盈亏或相对盈亏）
        if is_absolute:
            sorted_data = sorted(players_data, key=lambda x: x['absolute_profit_loss'], reverse=True)
        else:
            sorted_data = sorted(players_data, key=lambda x: x['relative_profit_loss'], reverse=True)
        
        # 插入新数据
        for rank, player_data in enumerate(sorted_data, 1):
            self.database_manager.insert("tb_leaderboard", {
                "player_xuid": player_data['player_xuid'],
                "total_wealth": player_data['total_wealth'],
                "holdings_value": player_data['holdings_value'],
                "balance": player_data['balance'],
                "total_buy": player_data['total_buy'],
                "total_sell": player_data['total_sell'],
                "absolute_profit_loss": player_data['absolute_profit_loss'],
                "relative_profit_loss": player_data['relative_profit_loss'],
                "is_absolute": is_absolute,
                "last_updated": time.time(),
                "rank": rank
            })

        
    def insert_qq_send_log(self, date_str):
        exist_log = self.database_manager.query_all(
            'SELECT * FROM tb_qq_notice WHERE send_date = ? ', (date_str,)
        )

        if len(exist_log) != 0:
            return False
        
        try:
            self.database_manager.insert("tb_qq_notice", {
                "send_date": date_str
            })
            return True
        except Exception as ex:
            print(f"更新QQ日志表错误:{ex}")
            return False

    def delete_qq_send_log(self, date_str):
        """发送失败时清除当日标记，便于后续排行榜任务重试。"""
        try:
            self.database_manager.execute(
                "DELETE FROM tb_qq_notice WHERE send_date = ?",
                (date_str,),
            )
            return True
        except Exception as ex:
            print(f"删除QQ日志错误:{ex}")
            return False
