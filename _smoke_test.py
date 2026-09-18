# -*- coding: utf-8 -*-
"""v0.6.0 合约升级冒烟测试：stub endstone/yfinance 后导入全部模块，并对 DAO/数学做单测。"""
import os
import sys
import time
import types
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _stub_class(name):
    return type(name, (), {"__init__": lambda self, *a, **k: None})


# ---- stub endstone ----
event_handlerDecorator = lambda *a, **k: (lambda f: f)
_stub_module("endstone")
_stub_module("endstone.command", Command=_stub_class("Command"), CommandSender=_stub_class("CommandSender"))
_stub_module("endstone.event", EventPriority=types.SimpleNamespace(HIGH=2), ServerLoadEvent=_stub_class("ServerLoadEvent"),
             event_handler=event_handlerDecorator)
_stub_module("endstone.plugin", Plugin=_stub_class("Plugin"))
_stub_module("endstone.form", ActionForm=_stub_class("ActionForm"), ModalForm=_stub_class("ModalForm"),
             Label=_stub_class("Label"), TextInput=_stub_class("TextInput"), Dropdown=_stub_class("Dropdown"))
_stub_module("yfinance", Ticker=_stub_class("Ticker"), set_config=lambda **k: None,
             WebSocket=_stub_class("WebSocket"))

from endstone_up_and_down.databaseManager import DatabaseManager
from endstone_up_and_down.stockDao import StockDao
from endstone_up_and_down.setting_manager import StockSettingManager
from endstone_up_and_down import up_and_down_plugin
from endstone_up_and_down import ui_manager

print("[1] 全模块导入 OK（含插件类定义）")

# ---- DAO 单测：内存库 ----
tmp_db = os.path.join(tempfile.gettempdir(), f"uad_test_{int(time.time())}.db")
db = DatabaseManager(tmp_db)
dao = StockDao(db)
dao.init_tables()
print("[2] init_tables OK（含 tb_margin_position）")

# 开仓
pid = dao.create_margin_position("xuid_A", "AAPL", "long", 5, 100.0, 10, 50.0, 2.5)
assert pid == 1, pid
pos = dao.get_margin_position(pid)
assert pos["status"] == "open" and pos["share"] == 10 and pos["margin"] == 100.0

# 部分平仓：价格涨到 52 → pnl = (52-50)*10 = 20
from decimal import Decimal
price = Decimal("52")
pnl = (price - Decimal(str(pos["entry_price"]))) * Decimal(str(pos["share"]))
interest = Decimal("0.5")
close_fee = price * Decimal(5) * Decimal("0.01")  # 5股 * 52 * 1%
returned = Decimal(str(pos["margin"])) * Decimal("0.5") + pnl * Decimal("0.5") - close_fee - interest * Decimal("0.5")
open_fee_part = Decimal("2.5") * Decimal("0.5")
realized = returned - Decimal(str(pos["margin"])) * Decimal("0.5") - open_fee_part

remain, closed_row = dao.settle_margin_position(pid, 5, price, close_fee, interest * Decimal("0.5"),
                                                Decimal(0), realized, "manual")
assert remain["share"] == 5 and abs(remain["margin"] - 50.0) < 1e-6, remain
assert closed_row["status"] == "closed" and closed_row["share"] == 5
assert abs(closed_row["realized_pnl"] - float(realized)) < 1e-6
print(f"[3] 部分平仓 OK：remain=5股/保证金50，closed realized_pnl={closed_row['realized_pnl']:.4f}（期望 {float(realized):.4f}）")

# 全部平仓剩余 5 股：价格 48 → pnl = (48-50)*5 = -10
price2 = Decimal("48")
pos2 = dao.get_margin_position(pid)
pnl2 = (price2 - Decimal(str(pos2["entry_price"]))) * Decimal(str(pos2["share"]))
close_fee2 = price2 * Decimal(5) * Decimal("0.01")
returned2 = Decimal(str(pos2["margin"])) + pnl2 - close_fee2
realized2 = returned2 - Decimal(str(pos2["margin"])) - Decimal(str(pos2["open_fee"]))
_, closed2 = dao.settle_margin_position(pid, 5, price2, close_fee2, Decimal(0), Decimal(0), realized2, "manual")
assert closed2["status"] == "closed" and dao.get_margin_position(pid)["status"] == "closed"
print(f"[4] 全部平仓 OK：realized_pnl={closed2['realized_pnl']:.4f}（期望 {float(realized2):.4f}）")

# 空头强平结算：entry 50, margin 100, share 10（另一仓）
pid2 = dao.create_margin_position("xuid_B", "TSLA", "short", 10, 100.0, 20, 50.0, 5.0)
price3 = Decimal("56")  # 涨 12% → pnl = (50-56)*20 = -120
p_pos = dao.get_margin_position(pid2)
pnl3 = (Decimal(str(p_pos["entry_price"])) - price3) * Decimal(str(p_pos["share"]))
liq_fee = price3 * Decimal(20) * Decimal("0.01")
equity = Decimal("100") + pnl3
returned3 = max(equity - liq_fee, Decimal(0))
realized3 = returned3 - Decimal("100") - Decimal("5")
_, closed3 = dao.settle_margin_position(pid2, 20, price3, Decimal(0), Decimal(0), liq_fee, realized3, "liquidation")
assert closed3["status"] == "liquidated"
# equity = -20, liq_fee = 11.2 → returned 0 → realized = -105
assert abs(closed3["realized_pnl"] - (-105.0)) < 1e-6, closed3["realized_pnl"]
print(f"[5] 空头强平 OK：equity={float(equity)}，强平费={float(liq_fee)}，realized_pnl={closed3['realized_pnl']}（期望 -105）")

# ---- 排行榜公式 ----
dao.increase_balance("xuid_A", 1000.0)
dao.increase_balance("xuid_B", 1000.0)

def fake_price(stock):
    return {"AAPL": Decimal("52"), "TSLA": Decimal("56")}.get(stock), True

players = dao.get_all_players_profit_loss(fake_price, contract_interest_hourly=0.0)
by_xuid = {p["player_xuid"]: p for p in players}
# xuid_A：合约 closed realized 合计 = realized + realized2；无 open 仓位
a_closed = dao.get_closed_margin_pnl_total("xuid_A")
assert abs(by_xuid["xuid_A"]["absolute_profit_loss"] - a_closed) < 1e-6
# xuid_B：closed = -105
assert abs(by_xuid["xuid_B"]["absolute_profit_loss"] - (-105.0)) < 1e-6
# total_buy = 合约 deployed（B 一笔：100+5）
assert abs(by_xuid["xuid_B"]["total_buy"] - 105.0) < 1e-6
print(f"[6] 排行榜公式 OK：A={by_xuid['xuid_A']['absolute_profit_loss']:.4f}，B={by_xuid['xuid_B']['absolute_profit_loss']:.4f}，B投入={by_xuid['xuid_B']['total_buy']}")

# 未平仓财富计入：给 A 开新仓 margin 80, entry 50, share 8 → 现价 52 → pnl=16
pid_open = dao.create_margin_position("xuid_A", "AAPL", "long", 5, 80.0, 8, 50.0, 2.0)
players = dao.get_all_players_profit_loss(fake_price, contract_interest_hourly=0.0)
a = [p for p in players if p["player_xuid"] == "xuid_A"][0]
expect_pl = a_closed + 16.0 - 2.0  # closed + pnl - open_fee
assert abs(a["absolute_profit_loss"] - expect_pl) < 1e-6, (a["absolute_profit_loss"], expect_pl)
assert abs(a["total_wealth"] - (1000.0 + 80.0 + 16.0)) < 1e-6, a["total_wealth"]
print(f"[7] 未平仓计入 OK：abs_pl={a['absolute_profit_loss']:.4f}（期望 {expect_pl}），wealth={a['total_wealth']:.2f}（期望 1096.00）")

# ---- 设置管理器 ----
cfg_dir = tempfile.mkdtemp()
sm = StockSettingManager(cfg_dir)
assert sm.get_contract_max_leverage() == 10
assert sm.get_contract_leverage_options() == [2, 3, 5, 10]
assert sm.get_contract_maintenance_rate() == 10.0
assert sm.get_contract_interest_hourly() == 0.01
assert sm.get_contract_liquidation_fee_rate() == 1.0
assert sm.get_contract_min_margin() == 100.0
assert sm.get_contract_check_interval() == 20
assert sm.get_contract_warning_rate() == 30.0
assert os.path.exists(os.path.join(cfg_dir, "stock_setting.yml"))
print("[8] 设置管理器 OK（默认值 + 自动落盘）")

# ---- 插件静态数学方法 ----
PnL = up_and_down_plugin.UpAndDownPlugin._calc_contract_pnl_interest
LiqP = up_and_down_plugin.UpAndDownPlugin._calc_contract_liquidation_price
pos_view = {"direction": "short", "entry_price": 50.0, "share": 20, "margin": 100.0,
            "open_time": time.time() - 3600}
pnl, interest = PnL(pos_view, 56.0, 0.01)
assert float(pnl) == -120.0
assert abs(float(interest) - (1000 - 100) * 0.01 / 100 * 1.0) < 1e-9  # 借入900 * 0.01% * 1h = 0.09
lp = LiqP(pos_view, 10)
assert abs(float(lp) - (50 + 100 * 90 / 100 / 20)) < 1e-9  # 50 + 0.9*5 = 54.5
print(f"[9] 插件数学 OK：short pnl={float(pnl)}，利息={float(interest):.2f}，强平价={float(lp)}")

# ---- 追加保证金：DAO 层 ----
# pid_open（xuid_A AAPL long, margin 80, entry 50, share 8）
dao.set_margin_warned(pid_open, 1)
assert dao.get_margin_position(pid_open)["warned"] == 1
players = dao.get_all_players_profit_loss(fake_price, contract_interest_hourly=0.0)
a_before = [p for p in players if p["player_xuid"] == "xuid_A"][0]
# dao.add_margin 语义：写入追加后的保证金总额（插件侧先算好 80+60）
dao.add_margin(pid_open, 140.0)
pos3 = dao.get_margin_position(pid_open)
assert abs(pos3["margin"] - 140.0) < 1e-6 and pos3["warned"] == 0
players = dao.get_all_players_profit_loss(fake_price, contract_interest_hourly=0.0)
a_after = [p for p in players if p["player_xuid"] == "xuid_A"][0]
# DAO 层只加保证金、不动余额：财富 +60，盈亏不变（盈亏不含保证金项）
assert abs(a_after["total_wealth"] - a_before["total_wealth"] - 60.0) < 1e-6
assert abs(a_before["absolute_profit_loss"] - a_after["absolute_profit_loss"]) < 1e-6
print("[10] 追加保证金 DAO OK：margin 80→140，预警复位，盈亏不受影响")

# ---- 追加保证金：插件方法端到端 ----
plug = up_and_down_plugin.UpAndDownPlugin()
plug.stock_dao = dao
plug.setting_manager = sm
plug.server = types.SimpleNamespace(online_players=[])
plug.get_stock_last_price = lambda stock, period="1d", interval="1m", return_period=False, prepost=True: (Decimal("44"), True)

dao.increase_balance("xuid_A", 500.0)
liq_before = float(LiqP(dao.get_margin_position(pid_open), 10.0))
# 参照点：紧贴插件调用前（价格52）
players = dao.get_all_players_profit_loss(fake_price, contract_interest_hourly=0.0)
a_ref = [p for p in players if p["player_xuid"] == "xuid_A"][0]
msgs = []
sender_stub = types.SimpleNamespace(send_message=lambda m: msgs.append(m))
ok, msg = plug.add_margin("xuid_A", sender_stub, pid_open, Decimal("50"))
assert ok, msg
assert len(msgs) == 1
pos3 = dao.get_margin_position(pid_open)
assert abs(pos3["margin"] - 190.0) < 1e-6
liq_after = float(LiqP(pos3, 10.0))
assert liq_after < liq_before  # 多头跌了，强平价应更低（更远）
assert abs(dao.get_balance("xuid_A") - 1450.0) < 1e-6  # 1000 + 500 - 50
# 现金流留痕
orders = dao.get_orders("xuid_A", page=0, page_size=5)
assert orders[0]["type"] == "contract_add_margin" and abs(orders[0]["total"] - 50.0) < 1e-6
# 他人仓位不可追加
ok2, _ = plug.add_margin("xuid_B", sender_stub, pid_open, Decimal("50"))
assert not ok2
# 已平仓仓位不可追加
ok3, _ = plug.add_margin("xuid_A", sender_stub, 1, Decimal("50"))
assert not ok3
# 插件层财富守恒：余额-50 与保证金+50 抵消，盈亏不变
players = dao.get_all_players_profit_loss(fake_price, contract_interest_hourly=0.0)
a_plugin = [p for p in players if p["player_xuid"] == "xuid_A"][0]
assert abs(a_plugin["total_wealth"] - a_ref["total_wealth"]) < 1e-6
assert abs(a_plugin["absolute_profit_loss"] - a_ref["absolute_profit_loss"]) < 1e-6
print(f"[11] 追加保证金插件 OK：强平价 {liq_before}→{liq_after}，余额={dao.get_balance('xuid_A')}，财富守恒，留痕/越权/已平仓校验通过")

print("\n=== 全部冒烟测试通过 ===")
