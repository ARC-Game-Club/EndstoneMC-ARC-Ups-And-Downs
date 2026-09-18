# -*- coding: utf-8 -*-
"""
v1.0.0 合约系统全链路仿真测试。

stub endstone/yfinance（含可交互的桩表单），模拟真实玩家操作路径：
UI 表单提交 → execute_command（含玩家锁）→ DAO → 强平引擎 → 排行榜。
核心审计不变量：任意时刻 余额 == 充值合计 + Σ已平仓 realized_pnl。
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ---------------- 桩：endstone 表单（可交互） ----------------
class StubLabel:
    def __init__(self, text="", **k):
        self.text = text


class StubTextInput:
    def __init__(self, label="", placeholder="", default_value="", **k):
        self.label, self.placeholder, self.default_value = label, placeholder, default_value


class StubDropdown:
    def __init__(self, label="", options=None, default_index=0, **k):
        self.label, self.options, self.default_index = label, options or [], default_index


class StubActionForm:
    def __init__(self, title="", content="", on_close=None, **k):
        self.title, self.content, self.on_close = title, content, on_close
        self.buttons = []

    def add_button(self, text, on_click=None, **k):
        self.buttons.append((text, on_click))

    def click(self, sender, text):
        for btn_text, handler in self.buttons:
            if btn_text == text:
                assert handler is not None, f"按钮「{text}」无回调"
                handler(sender)
                return
        raise AssertionError(f"表单「{self.title}」没有按钮「{text}」，现有: {[b[0] for b in self.buttons]}")


class StubModalForm:
    def __init__(self, title="", controls=None, on_submit=None, on_close=None, **k):
        self.title, self.controls, self.on_submit, self.on_close = title, controls or [], on_submit, on_close

    def submit(self, sender, values):
        self.on_submit(sender, json.dumps(values))


def _stub_module_(forms):
    _stub_module("endstone")
    _stub_module("endstone.command", Command=type("C", (), {}), CommandSender=type("S", (), {}))
    _stub_module("endstone.event", EventPriority=types.SimpleNamespace(HIGH=2),
                 ServerLoadEvent=type("E", (), {}),
                 event_handler=lambda *a, **k: (lambda f: f))
    _stub_module("endstone.plugin", Plugin=type("P", (), {"__init__": lambda self, *a, **k: None}))
    _stub_module("endstone.form", ActionForm=StubActionForm, ModalForm=StubModalForm,
                 Label=StubLabel, TextInput=StubTextInput, Dropdown=StubDropdown)
    _stub_module("yfinance", Ticker=type("T", (), {}), set_config=lambda **k: None,
                 WebSocket=type("W", (), {}))


_stub_module_(None)

from endstone_up_and_down.databaseManager import DatabaseManager
from endstone_up_and_down.stockDao import StockDao
from endstone_up_and_down.setting_manager import StockSettingManager
from endstone_up_and_down.lockManager import LockManager
from endstone_up_and_down.favorites_manager import FavoritesManager
from endstone_up_and_down.player_settings_manager import PlayerSettingsManager
from endstone_up_and_down.ui_manager import UIManager
from endstone_up_and_down import up_and_down_plugin

# ---------------- 桩：线程调度（可排水） ----------------
_real_thread = threading.Thread
_spawned = []


class InstrumentedThread(_real_thread):
    def start(self):
        _spawned.append(self)
        super().start()


threading.Thread = InstrumentedThread


def drain():
    """等待所有已派生线程结束（含派生链）。"""
    while _spawned:
        t = _spawned.pop(0)
        t.join(timeout=60)
        assert not t.is_alive(), "线程超时未结束"


# ---------------- 桩：玩家 / 服务器 / 日志 ----------------
class StubPlayer:
    def __init__(self, name, xuid):
        self.name, self.xuid = name, xuid
        self.sent_forms = []
        self.messages = []

    def send_form(self, form):
        self.sent_forms.append(form)

    def send_message(self, msg):
        self.messages.append(str(msg))

    def send_error_message(self, msg):
        self.messages.append(f"[ERR]{msg}")

    def last_form(self):
        assert self.sent_forms, f"{self.name} 没有收到任何表单"
        return self.sent_forms[-1]


class StubScheduler:
    def run_task(self, plugin, fn, delay=0, period=None):
        fn()


class StubServer:
    def __init__(self, players):
        self.online_players = list(players)
        self.scheduler = StubScheduler()

    def get_player(self, name):
        for p in self.online_players:
            if p.name == name:
                return p
        return None


class StubLogger:
    def __init__(self):
        self.records = []

    def _rec(self, level, msg):
        self.records.append((level, str(msg)))

    def info(self, m): self._rec("I", m)

    def warning(self, m): self._rec("W", m)

    def error(self, m): self._rec("E", m)


# ---------------- 可编程行情 ----------------
PRICES = {"AAPL": 50.0, "TSLA": 100.0}


def fake_price(stock, period="1d", interval="1m", return_period=False):
    if return_period:
        return [PRICES.get(stock, 0)], True
    return Decimal(str(PRICES[stock])), True


# ---------------- 组装插件实例 ----------------
tmp_db = os.path.join(tempfile.gettempdir(), f"uad_sim_{int(time.time())}.db")
cfg_dir = tempfile.mkdtemp()

db = DatabaseManager(tmp_db)
dao = StockDao(db)
dao.init_tables()
sm = StockSettingManager(cfg_dir)

alice = StubPlayer("Alice", "XUID_ALICE")
bob = StubPlayer("Bob", "XUID_BOB")

plug = up_and_down_plugin.UpAndDownPlugin()
plug.database_manager = db
plug.stock_dao = dao
plug.setting_manager = sm
plug.lock_manager = LockManager()
plug.favorites_manager = FavoritesManager(db)
plug.player_settings_manager = PlayerSettingsManager(db)
plug.ui_manager = UIManager(plug)
plug.server = StubServer([alice, bob])
plug.logger = StubLogger()
plug.economy_plugin = types.SimpleNamespace(
    get_player_money=lambda p: 999999.0,
    decrease_player_money=lambda p, a: None,
    increase_player_money=lambda p, a: None,
)
plug.get_stock_last_price = fake_price
ui = plug.ui_manager

DEPOSITS = {}


def deposit(player, amount):
    dao.increase_balance(player.xuid, amount)
    DEPOSITS[player.xuid] = DEPOSITS.get(player.xuid, 0.0) + amount


def audit(tag):
    """核心不变量：余额 == 充值 + Σ已平仓净盈亏 - Σ未平仓(保证金+开仓费)。"""
    for xuid, dep in DEPOSITS.items():
        closed = dao.get_closed_margin_pnl_total(xuid)
        locked = sum(float(p["margin"]) + float(p["open_fee"])
                     for p in dao.get_open_margin_positions(xuid))
        balance = float(dao.get_balance(xuid))
        assert abs(balance - (dep + closed - locked)) < 0.01, (
            f"[{tag}] {xuid} 资金账不平：余额{balance} != 充值{dep} + 已平{closed:.2f} - 占用{locked:.2f}")


def near(a, b, tol=0.01):
    assert abs(float(a) - float(b)) < tol, f"{a} != {b}"


print("== 场景0：激活与主面板 UI ==")
deposit(alice, 10000.0)
ui.show_main_panel(alice)
drain()
main_form = alice.last_form()
assert any(t.startswith("合约交易") for t, _ in main_form.buttons), "主面板缺少合约交易入口"

print("== 场景1：UI 开多全流程（表单提交→预览→确认） ==")
ui.show_contract_open_panel(alice, "AAPL", direction_index=0)
drain()
open_modal = alice.last_form()
assert open_modal.title == "合约开仓"
# 控件: [Label, 股票, 方向, 保证金, 杠杆]；杠杆选 index1 = 3x
open_modal.submit(alice, [None, "AAPL", 0, "1000", 1])
drain()
confirm_form = alice.last_form()
assert "合约开仓确认" in confirm_form.title
assert "60" in confirm_form.content, f"预览应含 60 股: {confirm_form.content}"
confirm_form.click(alice, "确认开仓")
drain()
result_form = alice.last_form()
assert "开仓成功" in result_form.title, result_form.title

positions = dao.get_open_margin_positions(alice.xuid)
assert len(positions) == 1
pos = positions[0]
pid_long = pos["id"]
near(pos["margin"], 1000)
near(pos["share"], 60)          # int(1000*3/50)
near(pos["entry_price"], 50)
near(pos["open_fee"], 30)       # 3000 * 1%
near(dao.get_balance(alice.xuid), 10000 - 1030)
print(f"   仓位#{pid_long}: 60股@50, 3x, 保证金1000+费30, 余额8970 ✓")

print("== 场景2：仓位详情 UI + 追加保证金 UI 全流程 ==")
ui.show_contract_position_detail(alice, pid_long)
drain()
detail = alice.last_form()
assert f"#{pid_long}" in detail.title
detail.click(alice, "追加保证金")
drain()
add_modal = alice.last_form()
assert "追加保证金" in add_modal.title
add_modal.submit(alice, [None, "200"])
drain()
add_confirm = alice.last_form()
assert "1200" in add_confirm.content  # 保证金预览 1000+200=1200
add_confirm.click(alice, "确认追加")
drain()
assert "追加成功" in alice.last_form().title
near(dao.get_margin_position(pid_long)["margin"], 1200)
near(dao.get_balance(alice.xuid), 8970 - 200)
audit("场景2")
print(f"   保证金 1000→1200, 余额 8970→8770 ✓")

print("== 场景3：部分平仓 UI 全流程 ==")
PRICES["AAPL"] = 52.0
ui.show_contract_position_detail(alice, pid_long)
drain()
alice.last_form().click(alice, "部分平仓")
drain()
partial_modal = alice.last_form()
partial_modal.submit(alice, [None, "20"])
drain()
alice.last_form().click(alice, "确认平仓 20/60 股")
drain()
assert "平仓成功" in alice.last_form().title
remain = dao.get_margin_position(pid_long)
closed_part = [p for p in dao.get_margin_positions(alice.xuid, exclude_open=True) if p["share"] == 20]
assert len(closed_part) == 1 and remain["status"] == "open" and remain["share"] == 40
# 20股@52: pnl=(52-50)*20=40, close_fee=52*20*1%=10.4, margin_part=1200/3=400, open_fee_part=10
# returned=400+40-10.4=429.6, realized=429.6-400-10=19.6
near(closed_part[0]["realized_pnl"], 19.6)
audit("场景3")
print(f"   拆行: 余40股, 已平20股 realized=19.6 ✓")

print("== 场景4：命令行做空 → 跌了平仓获利 ==")
deposit(bob, 5000.0)
plug.execute_command(bob, ["short", "TSLA", "500", "5"], False)
drain()
bob_msgs = bob.messages[:]
assert any("合约开空成功" in m for m in bob.messages), bob.messages[-3:]
pos_b = dao.get_open_margin_positions(bob.xuid)[0]
near(pos_b["share"], 25)        # int(500*5/100)
near(pos_b["open_fee"], 25)     # 2500*1%
near(dao.get_balance(bob.xuid), 5000 - 525)

PRICES["TSLA"] = 90.0
plug.execute_command(bob, ["close", str(pos_b["id"])], False)
drain()
assert any("平仓成功" in m for m in bob.messages)
# pnl=(100-90)*25=250, close_fee=90*25*1%=22.5, returned=500+250-22.5=727.5
# realized=727.5-500-25=202.5
near(dao.get_closed_margin_pnl_total(bob.xuid), 202.5)
near(dao.get_balance(bob.xuid), 4475 + 727.5)
audit("场景4")
print(f"   空头 25股@100→90, realized=202.5, 结算727.5 ✓")

print("== 场景5：强平引擎（预警→强平→通知） ==")
# Alice 多头剩余: 40股, entry 50, 保证金 800（1200 的 2/3），预警线=240，强平线=80
def check_now():
    plug._contract_price_cache = {}  # 清 60s 价格缓存，模拟价格随时间推进
    plug.check_contract_positions()
    drain()

for price in (45.0, 42.0, 39.0):
    PRICES["AAPL"] = price
    check_now()
    assert not any("【合约预警】" in m for m in alice.messages), f"价格{price}不应预警"
    assert dao.get_margin_position(pid_long)["status"] == "open"
PRICES["AAPL"] = 36.0  # 权益=800-560=240 ≤ 预警线
check_now()
assert any("【合约预警】" in m for m in alice.messages), "应触发预警"
assert dao.get_margin_position(pid_long)["warned"] == 1

PRICES["AAPL"] = 35.0  # 权益=200 > 强平线80，仍存活
check_now()
assert dao.get_margin_position(pid_long)["status"] == "open"
PRICES["AAPL"] = 32.0  # 权益=800-720=80 ≤ 强平线
check_now()
liq_pos = dao.get_margin_position(pid_long)
assert liq_pos["status"] == "liquidated", liq_pos["status"]
assert any("强制平仓" in m for m in alice.messages)
# equity=80；平仓手续费=32*40*1%=12.8，强平费再收12.8 → returned=800-720-12.8-12.8=54.4
# realized=54.4-800-20(开仓费分摊)=-765.6
near(liq_pos["realized_pnl"], -765.6)
near(liq_pos["liquidation_fee"], 12.8)
audit("场景5")
warned_count = sum(1 for lvl, m in plug.logger.records if "合约强平" in m)
assert warned_count >= 1, "强平应写日志"
print(f"   预警一次→强平@32, returned=54.4(含平仓费+强平费各12.8), realized=-765.6 ✓")

print("== 场景6：强平后 UI（仓位列表/历史/结算单/订单页） ==")
ui.show_contract_positions_panel(alice)
drain()
assert "我的仓位" in alice.last_form().title
ui.show_contract_history_panel(alice)
drain()
hist = alice.last_form()
assert "仓位历史" in hist.title
liq_buttons = [t for t, _ in hist.buttons if "爆仓" in t]
assert liq_buttons, f"历史列表应有爆仓记录: {[t for t, _ in hist.buttons]}"
hist.click(alice, liq_buttons[0])
drain()
assert "结算单" in alice.last_form().title and "爆仓" in alice.last_form().content
plug.execute_command(alice, ["positions"], False)
drain()
plug.execute_command(alice, ["long", "AAPL", "100", "2"], False)  # 再开一笔供 account 展示
drain()
plug.execute_command(alice, ["account"], False)
drain()
assert any("合约持仓 1 笔" in m for m in alice.messages), alice.messages[-3:]
print("   仓位列表/历史/结算单/positions/account 全部渲染无异常 ✓")

print("== 场景7：越权与边界 ==")
plug.execute_command(bob, ["close", str(pid_long)], False)
drain()
assert any("仓位 #{} 不存在".format(pid_long) in m or "不存在" in m for m in bob.messages[-2:])
plug.execute_command(bob, ["margin", "9999", "100"], False)
drain()
assert any("不存在" in m for m in bob.messages[-2:])
plug.execute_command(bob, ["long", "AAPL", "10", "7"], False)
drain()
assert any("杠杆倍数仅支持" in m for m in bob.messages[-2:])
plug.execute_command(bob, ["long", "AAPL", "50"], False)  # 低于最低保证金
drain()
assert any("保证金最低" in m for m in bob.messages[-2:])
audit("场景7")
print("   越权平仓/不存在仓位/非法杠杆/低于最低保证金 全部拒绝 ✓")

print("== 场景8：排行榜（含合约盈亏） ==")
players = dao.get_all_players_profit_loss(fake_price, sm.get_contract_interest_hourly())
by = {p["player_xuid"]: p for p in players}
# Alice: 已平 realized(19.6-634) + 开仓浮动: 40股@entry50,现价35 → pnl=-600, margin余800? 开仓费余20
a_closed = dao.get_closed_margin_pnl_total(alice.xuid)
a_open = [p for p in dao.get_open_margin_positions(alice.xuid)]
a_expect = a_closed
for p in a_open:
    pnl = (Decimal(str(PRICES[p["stock_name"]])) - Decimal(str(p["entry_price"]))) * p["share"]
    a_expect += float(pnl) - float(p["open_fee"])
near(by[alice.xuid]["absolute_profit_loss"], a_expect)
# Bob: 无未平仓, realized=202.5, 余额=5202.5
near(by[bob.xuid]["absolute_profit_loss"], 202.5)
near(by[bob.xuid]["total_wealth"], float(dao.get_balance(bob.xuid)))
print(f"   Alice盈亏={by[alice.xuid]['absolute_profit_loss']:.2f}, Bob盈亏=202.5, 财富=余额 ✓")

print("== 场景9：最终资金审计 ==")
audit("最终")
alice_bal = float(dao.get_balance(alice.xuid))
alice_closed = dao.get_closed_margin_pnl_total(alice.xuid)
alice_locked = sum(float(p["margin"]) + float(p["open_fee"]) for p in dao.get_open_margin_positions(alice.xuid))
assert abs(alice_bal - (10000.0 + alice_closed - alice_locked)) < 0.01
print(f"   Alice 余额{alice_bal} = 充值10000 + 已平{alice_closed:.2f} - 占用{alice_locked:.2f} ✓")

print("\n=== 仿真测试全部通过 ===")
