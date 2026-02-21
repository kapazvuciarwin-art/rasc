#!/usr/bin/env python3
"""rasc - MyCO2 監控網站"""

import threading
import asyncio
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from bleak import BleakScanner
from services.system_metrics import get_system_metrics
from services.storage import init_db as init_db_storage, save_reading as save_reading_storage, fetch_history, fetch_stats_24h

# 台灣時區 (UTC+8)
TAIWAN_TZ = timezone(timedelta(hours=8))

def now_taiwan():
    """獲取台灣時間"""
    return datetime.now(TAIWAN_TZ)

# 確保 print 輸出到標準輸出（systemd 會捕獲）
def log_debug(msg):
    """調試日誌"""
    print(f"[RASC DEBUG] {msg}", flush=True)

# sensirion-ble 庫（新解析方式）
try:
    from sensirion_ble import SensirionBluetoothDeviceData
    from bluetooth_sensor_state_data import BluetoothServiceInfo
    SENSIRION_BLE_AVAILABLE = True
    log_debug("sensirion-ble 庫已載入")
except ImportError:
    SENSIRION_BLE_AVAILABLE = False
    log_debug("sensirion-ble 庫未安裝，將使用原始解析方式")

# Telegram 通知模組
try:
    from telegram_notifier import check_and_notify, load_config, save_config, send_telegram_message
    TELEGRAM_AVAILABLE = True
    log_debug("Telegram 通知模組已載入")
except ImportError as e:
    TELEGRAM_AVAILABLE = False
    log_debug(f"Telegram 通知模組未載入: {e}")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'rasc-secret-key-2026'
socketio = SocketIO(app, cors_allowed_origins="*")

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"
DATABASE = "myco2_data.db"

# 全局變數存儲最新讀數
latest_reading = {
    'co2_ppm': None,
    'temperature_c': None,
    'humidity': None,
    'rssi': None,
    'cpu_usage_percent': None,
    'ram_usage_percent': None,
    'cpu_temp_c': None,
    'timestamp': None
}

monitoring_active = False
monitoring_thread = None
 
def save_reading(**kwargs):
    """儲存讀數到資料庫"""
    save_reading_storage(
        DATABASE,
        now_taiwan().isoformat(),
        **kwargs
    )


def update_latest_reading(
    co2_ppm=None,
    temperature_c=None,
    humidity=None,
    rssi=None,
    cpu_usage_percent=None,
    ram_usage_percent=None,
    cpu_temp_c=None
):
    """更新最新讀數並廣播"""
    global latest_reading
    
    if co2_ppm is not None:
        latest_reading['co2_ppm'] = co2_ppm
    if temperature_c is not None:
        latest_reading['temperature_c'] = temperature_c
    if humidity is not None:
        latest_reading['humidity'] = humidity
    if rssi is not None:
        latest_reading['rssi'] = rssi
    if cpu_usage_percent is not None:
        latest_reading['cpu_usage_percent'] = cpu_usage_percent
    if ram_usage_percent is not None:
        latest_reading['ram_usage_percent'] = ram_usage_percent
    if cpu_temp_c is not None:
        latest_reading['cpu_temp_c'] = cpu_temp_c
    
    latest_reading['timestamp'] = now_taiwan().isoformat()
    
    # 檢查並發送 Telegram 通知
    if TELEGRAM_AVAILABLE:
        try:
            check_and_notify(
                co2_ppm=co2_ppm,
                temperature_c=temperature_c,
                humidity=humidity,
                ram_usage_percent=ram_usage_percent
            )
        except Exception as e:
            log_debug(f"Telegram 通知檢查失敗: {e}")
    
    # 透過 WebSocket 廣播給所有客戶端
    socketio.emit('sensor_update', latest_reading)


def parse_with_sensirion_ble(manufacturer_data, rssi=-100):
    """使用 sensirion-ble 庫解析數據（新方式）
    
    Args:
        manufacturer_data: 製造商數據字典 {manufacturer_id: bytes}
        rssi: 訊號強度
    
    Returns:
        dict: {'co2_ppm': int, 'temperature_c': float, 'humidity': float} 或 None
    """
    if not SENSIRION_BLE_AVAILABLE:
        return None
    
    try:
        # 創建 BluetoothServiceInfo
        service_info = BluetoothServiceInfo(
            name=MYCO2_NAME,
            address=MYCO2_MAC,
            rssi=rssi,
            manufacturer_data=manufacturer_data,
            service_data={},
            service_uuids=[],
            source="rasc"
        )
        
        # 使用 sensirion-ble 解析
        parser = SensirionBluetoothDeviceData()
        
        if parser.supported(service_info):
            update = parser.update(service_info)
            
            # 提取感測器數據
            result = {}
            if hasattr(update, 'entity_values'):
                for device_key, sensor_value in update.entity_values.items():
                    key = device_key.key
                    value = sensor_value.native_value
                    
                    if key == 'carbon_dioxide':
                        result['co2_ppm'] = int(value) if value is not None else None
                    elif key == 'temperature':
                        result['temperature_c'] = float(value) if value is not None else None
                    elif key == 'humidity':
                        result['humidity'] = float(value) if value is not None else None
            
            if result:
                log_debug(f"sensirion-ble 解析結果: {result}")
                return result
    except Exception as e:
        log_debug(f"sensirion-ble 解析失敗: {e}")
    
    return None


async def monitor_myco2_async():
    """異步監控 MyCO2"""
    global monitoring_active
    
    while monitoring_active:
        try:
            # 尋找設備
            devices = await BleakScanner.discover(timeout=5)
            
            rssi = -100
            manufacturer_data = {}
            for device in devices:
                if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
                    if hasattr(device, 'details') and 'props' in device.details:
                        props = device.details['props']
                        rssi = props.get('RSSI', -100)
                        manufacturer_data = props.get('ManufacturerData', {})
                    break
            
            # ===== 啟用：sensirion-ble 庫解析（唯一啟用的解析方式） =====
            if manufacturer_data and SENSIRION_BLE_AVAILABLE:
                sensirion_result = parse_with_sensirion_ble(manufacturer_data, rssi)
                if sensirion_result:
                    system_metrics = get_system_metrics()
                    cpu_usage = system_metrics.get('cpu_usage_percent')
                    ram_usage = system_metrics.get('ram_usage_percent')
                    cpu_temp = (system_metrics.get('temperatures_c') or {}).get('cpu')
                    log_debug(f"使用 sensirion-ble 解析廣告數據成功: {sensirion_result}")
                    save_reading(
                        co2_ppm=sensirion_result.get('co2_ppm'),
                        temperature_c=sensirion_result.get('temperature_c'),
                        humidity=sensirion_result.get('humidity'),
                        rssi=rssi,
                        cpu_usage_percent=cpu_usage,
                        ram_usage_percent=ram_usage,
                        cpu_temp_c=cpu_temp,
                        raw_data=manufacturer_data.get(0x06d5, b'').hex() if 0x06d5 in manufacturer_data else ''
                    )
                    update_latest_reading(
                        co2_ppm=sensirion_result.get('co2_ppm'),
                        temperature_c=sensirion_result.get('temperature_c'),
                        humidity=sensirion_result.get('humidity'),
                        rssi=rssi,
                        cpu_usage_percent=cpu_usage,
                        ram_usage_percent=ram_usage,
                        cpu_temp_c=cpu_temp
                    )
            elif not SENSIRION_BLE_AVAILABLE:
                log_debug("警告：sensirion-ble 庫未安裝，無法解析數據")
            
            # 等待後繼續掃描（只使用 sensirion-ble 解析廣告數據）
            await asyncio.sleep(5)
                
        except Exception:
            await asyncio.sleep(5)


def monitor_myco2_thread():
    """在獨立線程中運行監控"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(monitor_myco2_async())


def start_monitoring():
    """啟動監控"""
    global monitoring_active, monitoring_thread
    
    if not monitoring_active:
        monitoring_active = True
        monitoring_thread = threading.Thread(target=monitor_myco2_thread, daemon=True)
        monitoring_thread.start()


# Flask 路由
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/latest')
def api_latest():
    """獲取最新讀數"""
    return jsonify(latest_reading)


@app.route('/api/system')
def api_system():
    """獲取樹莓派系統資訊"""
    return jsonify(get_system_metrics())


@app.route('/api/history')
def api_history():
    """獲取歷史數據"""
    try:
        hours = max(1, int(request.args.get('hours', 24)))
    except (TypeError, ValueError):
        hours = 24
    try:
        max_points = int(request.args.get('max_points', 0))
    except (TypeError, ValueError):
        max_points = 0
    max_points = max(0, min(max_points, 2000))
    since = now_taiwan() - timedelta(hours=hours)
    data = fetch_history(DATABASE, since.isoformat(), max_points)
    return jsonify(data)


@app.route('/api/stats')
def api_stats():
    """獲取統計數據"""
    since = now_taiwan() - timedelta(hours=24)
    return jsonify(fetch_stats_24h(DATABASE, since.isoformat()))


@app.route('/api/telegram/config', methods=['GET'])
def api_telegram_config_get():
    """獲取 Telegram 配置"""
    if not TELEGRAM_AVAILABLE:
        return jsonify({"error": "Telegram 模組未載入"}), 500
    
    try:
        config = load_config()
        # 隱藏敏感信息
        safe_config = config.copy()
        if safe_config.get("bot_token"):
            safe_config["bot_token"] = safe_config["bot_token"][:10] + "..." if len(safe_config["bot_token"]) > 10 else "***"
        return jsonify(safe_config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/telegram/config', methods=['POST'])
def api_telegram_config_set():
    """設定 Telegram 配置"""
    if not TELEGRAM_AVAILABLE:
        return jsonify({"error": "Telegram 模組未載入"}), 500
    
    try:
        data = request.get_json()
        config = load_config()
        
        # 更新配置
        if "enabled" in data:
            config["enabled"] = bool(data["enabled"])
        if "bot_token" in data:
            config["bot_token"] = str(data["bot_token"]).strip()
            log_debug(f"Telegram 配置: Bot token 已更新（長度: {len(config['bot_token'])}）")
        if "chat_id" in data:
            config["chat_id"] = str(data["chat_id"]).strip()
            log_debug(f"Telegram 配置: Chat ID 已更新: {config['chat_id']}")
        if "thresholds" in data:
            for sensor_type, threshold_config in data["thresholds"].items():
                if sensor_type in config["thresholds"]:
                    if "enabled" in threshold_config:
                        config["thresholds"][sensor_type]["enabled"] = bool(threshold_config["enabled"])
                    if "min" in threshold_config:
                        config["thresholds"][sensor_type]["min"] = float(threshold_config["min"]) if threshold_config["min"] is not None else None
                    if "max" in threshold_config:
                        config["thresholds"][sensor_type]["max"] = float(threshold_config["max"]) if threshold_config["max"] is not None else None
                    if "cooldown_minutes" in threshold_config:
                        config["thresholds"][sensor_type]["cooldown_minutes"] = int(threshold_config["cooldown_minutes"])
        
        if save_config(config):
            log_debug("Telegram 配置已保存")
            return jsonify({"success": True, "message": "配置已保存"})
        else:
            log_debug("Telegram 配置保存失敗")
            return jsonify({"error": "保存配置失敗"}), 500
    except Exception as e:
        log_debug(f"Telegram 配置設定異常: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/telegram/test', methods=['POST'])
def api_telegram_test():
    """測試 Telegram 通知"""
    if not TELEGRAM_AVAILABLE:
        log_debug("Telegram 測試失敗: 模組未載入")
        return jsonify({"error": "Telegram 模組未載入"}), 500
    
    try:
        config = load_config()
        bot_token = config.get("bot_token", "").strip()
        chat_id = config.get("chat_id", "").strip()
        
        log_debug(f"Telegram 測試: bot_token 長度={len(bot_token)}, chat_id={chat_id}")
        
        if not bot_token:
            log_debug("Telegram 測試失敗: Bot token 未設定")
            return jsonify({"error": "Bot token 未設定，請先填入 Bot Token"}), 400
        
        if not chat_id:
            log_debug("Telegram 測試失敗: Chat ID 未設定")
            return jsonify({"error": "Chat ID 未設定，請先填入 Chat ID"}), 400
        
        test_message = f"🧪 <b>MyCO2 測試通知</b>\n\n這是一條測試消息。\n時間: {now_taiwan().strftime('%Y-%m-%d %H:%M:%S')}"
        log_debug(f"Telegram 測試: 發送消息到 chat_id={chat_id}")
        success, result = send_telegram_message(bot_token, chat_id, test_message)
        
        if success:
            log_debug("Telegram 測試成功: 消息已發送")
            return jsonify({"success": True, "message": "測試消息已發送！請檢查您的 Telegram。"})
        else:
            log_debug(f"Telegram 測試失敗: {result}")
            return jsonify({"error": result}), 500
    except Exception as e:
        log_debug(f"Telegram 測試異常: {str(e)}")
        return jsonify({"error": f"測試失敗: {str(e)}"}), 500


@socketio.on('connect')
def handle_connect():
    """客戶端連接"""
    emit('sensor_update', latest_reading)
    print(f"客戶端已連接: {request.sid}")


@socketio.on('disconnect')
def handle_disconnect():
    """客戶端斷開"""
    print(f"客戶端已斷開: {request.sid}")


if __name__ == '__main__':
    # 初始化資料庫
    init_db_storage(DATABASE)
    
    # 啟動監控
    start_monitoring()
    
    # 啟動 Flask 服務
    print("\n" + "=" * 70)
    print("MyCO2 監控網站")
    print("=" * 70)
    print(f"請在瀏覽器開啟： http://0.0.0.0:5005")
    print(f"或從其他裝置：   http://<此機IP>:5005")
    print("=" * 70 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=5005, debug=False, allow_unsafe_werkzeug=True)
