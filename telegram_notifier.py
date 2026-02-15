#!/usr/bin/env python3
"""Telegram 通知模組"""

import requests
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from copy import deepcopy

# 台灣時區 (UTC+8)
TAIWAN_TZ = timezone(timedelta(hours=8))

def now_taiwan():
    """獲取台灣時間"""
    return datetime.now(TAIWAN_TZ)

# 配置文件路徑
CONFIG_FILE = Path(__file__).parent / "telegram_config.json"

# 預設配置
DEFAULT_CONFIG = {
    "enabled": False,
    "bot_token": "",
    "chat_id": "",
    "thresholds": {
        "co2_ppm": {
            "enabled": False,
            "min": None,
            "max": 1000,
            "cooldown_minutes": 30  # 冷卻時間（分鐘），避免重複通知
        },
        "temperature_c": {
            "enabled": False,
            "min": 10,
            "max": 30,
            "cooldown_minutes": 30
        },
        "humidity": {
            "enabled": False,
            "min": 30,
            "max": 70,
            "cooldown_minutes": 30
        }
    },
    "last_notification": {}  # 記錄上次通知時間
}

_CONFIG_CACHE = None
_CONFIG_MTIME = None


def _merge_with_default_config(config):
    """合併預設配置，確保欄位完整"""
    merged_config = deepcopy(DEFAULT_CONFIG)
    merged_config.update(config)
    for key in DEFAULT_CONFIG["thresholds"]:
        if key not in merged_config["thresholds"]:
            merged_config["thresholds"][key] = deepcopy(DEFAULT_CONFIG["thresholds"][key])
        else:
            for subkey in DEFAULT_CONFIG["thresholds"][key]:
                if subkey not in merged_config["thresholds"][key]:
                    merged_config["thresholds"][key][subkey] = DEFAULT_CONFIG["thresholds"][key][subkey]
    return merged_config


def load_config():
    """載入配置（含簡易快取）"""
    global _CONFIG_CACHE, _CONFIG_MTIME

    if CONFIG_FILE.exists():
        try:
            current_mtime = CONFIG_FILE.stat().st_mtime
            if _CONFIG_CACHE is not None and _CONFIG_MTIME == current_mtime:
                return deepcopy(_CONFIG_CACHE)

            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                merged_config = _merge_with_default_config(config)
                _CONFIG_CACHE = deepcopy(merged_config)
                _CONFIG_MTIME = current_mtime
                return deepcopy(merged_config)
        except Exception as e:
            print(f"[Telegram] 載入配置失敗: {e}")
            return deepcopy(DEFAULT_CONFIG)
    else:
        # 如果配置文件不存在，創建預設配置
        save_config(deepcopy(DEFAULT_CONFIG))
        return deepcopy(DEFAULT_CONFIG)


def save_config(config):
    """保存配置"""
    global _CONFIG_CACHE, _CONFIG_MTIME
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        _CONFIG_CACHE = _merge_with_default_config(config)
        _CONFIG_MTIME = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
        return True
    except Exception as e:
        print(f"[Telegram] 保存配置失敗: {e}")
        return False


def send_telegram_message(bot_token, chat_id, message):
    """發送 Telegram 消息"""
    if not bot_token or not chat_id:
        return False, "Bot token 或 Chat ID 未設定"
    
    # 清理輸入
    bot_token = bot_token.strip()
    chat_id = chat_id.strip()
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response_data = response.json()
        
        if response.status_code == 200:
            return True, "發送成功"
        else:
            # 解析 Telegram API 的錯誤信息
            error_description = "未知錯誤"
            if isinstance(response_data, dict):
                if "description" in response_data:
                    error_description = response_data["description"]
                elif "error_code" in response_data:
                    error_description = f"錯誤代碼 {response_data['error_code']}"
            
            return False, f"發送失敗: {error_description}"
    except requests.exceptions.Timeout:
        return False, "發送失敗: 請求超時，請檢查網絡連接"
    except requests.exceptions.ConnectionError:
        return False, "發送失敗: 無法連接到 Telegram API，請檢查網絡連接"
    except Exception as e:
        return False, f"發送失敗: {str(e)}"


def check_threshold(sensor_type, value, config):
    """檢查數值是否超過閾值"""
    if not config.get("enabled", False):
        return False, None
    
    threshold_config = config["thresholds"].get(sensor_type, {})
    if not threshold_config.get("enabled", False):
        return False, None
    
    if value is None:
        return False, None
    
    # 檢查最小值
    min_val = threshold_config.get("min")
    if min_val is not None and value < min_val:
        return True, f"{sensor_type} 低於最小值 {min_val}（當前值: {value:.2f}）"
    
    # 檢查最大值
    max_val = threshold_config.get("max")
    if max_val is not None and value > max_val:
        return True, f"{sensor_type} 超過最大值 {max_val}（當前值: {value:.2f}）"
    
    return False, None


def should_send_notification(sensor_type, config):
    """檢查是否應該發送通知（考慮冷卻時間）"""
    if not config.get("enabled", False):
        return False
    
    threshold_config = config["thresholds"].get(sensor_type, {})
    cooldown_minutes = threshold_config.get("cooldown_minutes", 30)
    
    last_notification = config.get("last_notification", {})
    last_time_str = last_notification.get(sensor_type)
    
    if not last_time_str:
        return True
    
    try:
        last_time = datetime.fromisoformat(last_time_str)
        elapsed = now_taiwan() - last_time
        if elapsed < timedelta(minutes=cooldown_minutes):
            return False
    except:
        pass
    
    return True


def update_last_notifications(sensor_types, config):
    """批次更新最後通知時間（一次寫檔）"""
    if "last_notification" not in config:
        config["last_notification"] = {}
    timestamp = now_taiwan().isoformat()
    for sensor_type in sensor_types:
        config["last_notification"][sensor_type] = timestamp
    save_config(config)


def check_and_notify(co2_ppm=None, temperature_c=None, humidity=None):
    """檢查數值並發送通知"""
    config = load_config()
    
    if not config.get("enabled", False):
        return
    
    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")
    
    if not bot_token or not chat_id:
        return
    
    notifications = []
    
    # 檢查 CO2
    if co2_ppm is not None:
        should_notify, message = check_threshold("co2_ppm", co2_ppm, config)
        if should_notify and should_send_notification("co2_ppm", config):
            notifications.append(("co2_ppm", message))
    
    # 檢查溫度
    if temperature_c is not None:
        should_notify, message = check_threshold("temperature_c", temperature_c, config)
        if should_notify and should_send_notification("temperature_c", config):
            notifications.append(("temperature_c", message))
    
    # 檢查濕度
    if humidity is not None:
        should_notify, message = check_threshold("humidity", humidity, config)
        if should_notify and should_send_notification("humidity", config):
            notifications.append(("humidity", message))
    
    # 發送通知
    if notifications:
        # 組合所有通知消息
        message_parts = ["<b>⚠️ MyCO2 感測器警報</b>\n"]
        notified_sensors = []
        for sensor_type, msg in notifications:
            message_parts.append(f"• {msg}")
            notified_sensors.append(sensor_type)

        # 只寫一次配置檔，降低 I/O 成本
        update_last_notifications(notified_sensors, config)
        
        message_parts.append(f"\n時間: {now_taiwan().strftime('%Y-%m-%d %H:%M:%S')}")
        
        full_message = "\n".join(message_parts)
        success, result = send_telegram_message(bot_token, chat_id, full_message)
        
        if success:
            print(f"[Telegram] 通知已發送: {full_message}")
        else:
            print(f"[Telegram] 通知發送失敗: {result}")
