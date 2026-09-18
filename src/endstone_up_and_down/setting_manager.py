"""
股票插件配置管理器
"""
import os
from pathlib import Path


class StockSettingManager:
    setting_dict = {}  # 类变量存储所有配置
    
    def __init__(self, main_path: str):
        """
        初始化配置管理器
        :param main_path: 插件主目录路径
        """
        self.setting_file_path = Path(main_path) / "stock_setting.yml"
        self._load_setting_file()
    
    def _load_setting_file(self):
        """加载配置文件"""
        # 创建配置目录（如果不存在）
        self.setting_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 创建配置文件（如果不存在）
        if not self.setting_file_path.exists():
            # 创建默认配置
            self._create_default_config()
        
        # 加载配置文件内容
        with self.setting_file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    StockSettingManager.setting_dict[key.strip()] = value.strip()
    
    def _create_default_config(self):
        """创建默认配置文件"""
        default_config = """# 股票插件配置文件
# Stock Plugin Configuration File

# VPN代理设置（留空则不使用代理）
# VPN Proxy Settings (leave empty to disable proxy)
# 格式: IP:端口 或 留空
# Format: IP:Port or leave empty
# 示例 / Example: 127.0.0.1:7890
proxy=127.0.0.1:5555

# 是否启用代理（true/false）
# Enable proxy (true/false)
enable_proxy=true

# 股票数据更新间隔（秒）
# Stock data update interval (seconds)
update_interval=60

# 交易手续费率（百分比，例如：2.0 表示2%）
# Trading fee rate (percentage, e.g.: 2.0 means 2%)
trading_fee_rate=1.0

# ===== 合约交易（做空/杠杆）设置 =====
# Contract trading (short/leverage) settings

# 杠杆上限（整数）
# Max leverage (int)
contract_max_leverage=10

# 可选杠杆档位（逗号分隔，不超过上限）
# Leverage options (comma separated, not exceeding max)
contract_leverage_options=2,3,5,10

# 维持保证金率（百分比）：权益 <= 保证金*该比例 时触发强平，10 表示亏损达保证金的90%强平
# Maintenance margin rate (percent): liquidate when equity <= margin * rate
contract_maintenance_rate=10

# 资金利息（百分比/小时）：按借入部分（仓位价值-保证金）每小时计息
# Interest rate (percent per hour) on the borrowed part (position value - margin)
contract_interest_hourly=0.01

# 强平手续费（占仓位价值百分比）
# Liquidation fee (percent of position value)
contract_liquidation_fee=1.0

# 最低保证金（元）
# Minimum margin per position
contract_min_margin=100

# 强平检测间隔（秒）
# Liquidation check interval (seconds)
contract_check_interval=20

# 低保证金预警线（权益占保证金百分比，低于时提醒一次）
# Warning threshold (equity/margin percent, notify once below)
contract_warning_rate=30
"""
        with self.setting_file_path.open("w", encoding="utf-8") as f:
            f.write(default_config)
        
        # 同时加载默认值到内存
        StockSettingManager.setting_dict["proxy"] = "127.0.0.1:5555"
        StockSettingManager.setting_dict["enable_proxy"] = "false"
        StockSettingManager.setting_dict["update_interval"] = "60"
        StockSettingManager.setting_dict["trading_fee_rate"] = "2.0"
    
    def get_setting(self, key: str, default_value: str = None):
        """
        获取配置项
        :param key: 配置键
        :param default_value: 默认值
        :return: 配置值
        """
        # 如果配置项不存在，添加它
        if key not in StockSettingManager.setting_dict:
            with self.setting_file_path.open("a", encoding="utf-8") as f:
                f.write(f"\n{key}=")
            StockSettingManager.setting_dict[key] = ""
        
        value = StockSettingManager.setting_dict[key]
        return default_value if not value else value
    
    def set_setting(self, key: str, value: str):
        """
        设置配置项
        :param key: 配置键
        :param value: 配置值
        """
        # 更新内存中的配置
        StockSettingManager.setting_dict[key] = str(value)
        
        # 重写整个文件
        with self.setting_file_path.open("w", encoding="utf-8") as f:
            for k, v in StockSettingManager.setting_dict.items():
                f.write(f"{k}={v}\n")
    
    def get_proxy_config(self):
        """
        获取代理配置
        :return: (是否启用代理, 代理地址) 或 (False, None)
        """
        enable_proxy = self.get_setting("enable_proxy", "true").lower() == "true"
        proxy = self.get_setting("proxy", "")
        
        if enable_proxy and proxy:
            return True, proxy
        return False, None
    
    def get_update_interval(self):
        """
        获取更新间隔（秒）
        :return: 更新间隔
        """
        try:
            return int(self.get_setting("update_interval", "60"))
        except ValueError:
            return 60
    
    def get_trading_fee_rate(self):
        """
        获取交易手续费率（百分比）
        :return: 手续费率，例如 2.0 表示 2%
        """
        try:
            return float(self.get_setting("trading_fee_rate", "1.0"))
        except ValueError:
            return 1.0

    def get_contract_max_leverage(self):
        """获取合约杠杆上限"""
        try:
            return int(self.get_setting("contract_max_leverage", "10"))
        except ValueError:
            return 10

    def ensure_contract_config(self):
        """
        首次加载时把合约配置项连同默认值写入配置文件，便于服主查看与调整。
        已存在但值为空的键（历史懒加载残留）也会补上默认值。
        """
        defaults = {
            "contract_max_leverage": "10",
            "contract_leverage_options": "2,3,5,10",
            "contract_maintenance_rate": "10",
            "contract_interest_hourly": "0.01",
            "contract_liquidation_fee": "1.0",
            "contract_min_margin": "100",
            "contract_check_interval": "20",
            "contract_warning_rate": "30",
        }
        for key, value in defaults.items():
            if not StockSettingManager.setting_dict.get(key):
                StockSettingManager.setting_dict[key] = value
                with self.setting_file_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n{key}={value}")

    def get_contract_leverage_options(self):
        """获取可选杠杆档位列表（去重、升序、过滤超上限）"""
        raw = self.get_setting("contract_leverage_options", "2,3,5,10") or "2,3,5,10"
        options = []
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                continue
            if 1 < value <= self.get_contract_max_leverage() and value not in options:
                options.append(value)
        options.sort()
        return options or [2, 3, 5, 10]

    def get_contract_maintenance_rate(self):
        """获取维持保证金率（百分比）：权益 <= 保证金*该比例 时强平"""
        try:
            return float(self.get_setting("contract_maintenance_rate", "10"))
        except ValueError:
            return 10.0

    def get_contract_interest_hourly(self):
        """获取合约资金利息（百分比/小时，按借入部分计息）"""
        try:
            return float(self.get_setting("contract_interest_hourly", "0.01"))
        except ValueError:
            return 0.01

    def get_contract_liquidation_fee_rate(self):
        """获取强平手续费率（占仓位价值百分比）"""
        try:
            return float(self.get_setting("contract_liquidation_fee", "1.0"))
        except ValueError:
            return 1.0

    def get_contract_min_margin(self):
        """获取单笔合约最低保证金"""
        try:
            return float(self.get_setting("contract_min_margin", "100"))
        except ValueError:
            return 100.0

    def get_contract_check_interval(self):
        """获取强平检测间隔（秒）"""
        try:
            return max(5, int(self.get_setting("contract_check_interval", "20")))
        except ValueError:
            return 20

    def get_contract_warning_rate(self):
        """获取低保证金预警线（权益占保证金百分比）"""
        try:
            return float(self.get_setting("contract_warning_rate", "30"))
        except ValueError:
            return 30.0

