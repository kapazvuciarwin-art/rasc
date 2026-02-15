#!/usr/bin/env python3
"""Telegram 通知模組"""

import os
import requests
import json
from datetime import datetime, timedelta
from pathlib import Path

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


def load_config():
    """載入配置"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合併預設配置，確保所有欄位都存在
                merged_config = DEFAULT_CONFIG.copy()
                merged_config.update(config)
                # 確保 thresholds 結構完整
                for key in DEFAULT_CONFIG["thresholds"]:
                    if key not in merged_config["thresholds"]:
                        merged_config["thresholds"][key] = DEFAULT_CONFIG["thresholds"][key].copy()
                    else:
                        for subkey in DEFAULT_CONFIG["thresholds"][key]:
                            if subkey not in merged_config["thresholds"][key]:
                                merged_config["thresholds"][key][subkey] = DEFAULT_CONFIG["thresholds"][key][subkey]
                return merged_config
        except Exception as e:
            print(f"[Telegram] 載入配置失敗: {e}")
            return DEFAULT_CONFIG.copy()
    else:
        # 如果配置文件不存在，創建預設配置
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """保存配置"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[Telegram] 保存配置失敗: {e}")
        return False


def send_telegram_message(bot_token, chat_id, message):
    """發送 Telegram 消息"""
    if not bot_token or not chat_id:
        return False, "Bot token 或 Chat ID 未設定"
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True, "發送成功"
        else:
            return False, f"發送失敗: {response.status_code} - {response.text}"
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
        elapsed = datetime.now() - last_time
        if elapsed < timedelta(minutes=cooldown_minutes):
            return False
    except:
        pass
    
    return True


def update_last_notification(sensor_type, config):
    """更新最後通知時間"""
    if "last_notification" not in config:
        config["last_notification"] = {}
    config["last_notification"][sensor_type] = datetime.now().isoformat()
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
        for sensor_type, msg in notifications:
            message_parts.append(f"• {msg}")
            update_last_notification(sensor_type, config)
        
        message_parts.append(f"\n時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        full_message = "\n".join(message_parts)
        success, result = send_telegram_message(bot_token, chat_id, full_message)
        
        if success:
            print(f"[Telegram] 通知已發送: {full_message}")
        else:
            print(f"[Telegram] 通知發送失敗: {result}")
