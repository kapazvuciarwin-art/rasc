#!/usr/bin/env python3
"""rasc - MyCO2 監控網站"""

import os
import sqlite3
import threading
import asyncio
import struct
import sys
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from bleak import BleakScanner, BleakClient

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

# 關鍵特徵值 UUID
CO2_CHAR_UUID = "00007001-b38d-4985-720e-0f993a68ee41"
TEMP_CHAR_UUID = "00007003-b38d-4985-720e-0f993a68ee41"
NOTIFY_CHAR_UUID = "00008004-b38d-4985-720e-0f993a68ee41"  # 20 bytes 通知數據，包含多個感測器讀數

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
_cpu_usage_prev = {'total': None, 'idle': None}


def get_db():
    """獲取資料庫連接"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def _read_cpu_usage_percent():
    """從 /proc/stat 計算 CPU 使用率（百分比）"""
    global _cpu_usage_prev
    try:
        with open('/proc/stat', 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
        parts = first_line.split()
        if len(parts) < 8 or parts[0] != 'cpu':
            return None

        values = [int(v) for v in parts[1:8]]
        idle = values[3] + values[4]  # idle + iowait
        total = sum(values)

        prev_total = _cpu_usage_prev['total']
        prev_idle = _cpu_usage_prev['idle']
        _cpu_usage_prev = {'total': total, 'idle': idle}

        if prev_total is None or prev_idle is None:
            # 第一次呼叫先回傳即時近似值
            if total <= 0:
                return None
            return round(max(0.0, min(100.0, (1 - (idle / total)) * 100.0)), 1)

        total_diff = total - prev_total
        idle_diff = idle - prev_idle
        if total_diff <= 0:
            return None

        usage = (1.0 - (idle_diff / total_diff)) * 100.0
        return round(max(0.0, min(100.0, usage)), 1)
    except Exception:
        return None


def _read_ram_usage_percent():
    """從 /proc/meminfo 計算 RAM 使用率（百分比）"""
    try:
        mem_total = None
        mem_available = None
        with open('/proc/meminfo', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    mem_total = int(line.split()[1])  # kB
                elif line.startswith('MemAvailable:'):
                    mem_available = int(line.split()[1])  # kB

        if not mem_total or mem_available is None:
            return None

        used = mem_total - mem_available
        if mem_total <= 0:
            return None

        return round(max(0.0, min(100.0, (used / mem_total) * 100.0)), 1)
    except Exception:
        return None


def _read_cpu_temp_c():
    """讀取 CPU 溫度（攝氏）"""
    candidates = [
        '/sys/class/thermal/thermal_zone0/temp',
        '/sys/devices/virtual/thermal/thermal_zone0/temp',
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    raw = f.read().strip()
                value = float(raw) / 1000.0
                return round(value, 1)
        except Exception:
            continue
    return None


def get_system_metrics():
    """讀取樹莓派系統資訊"""
    return {
        'cpu_usage_percent': _read_cpu_usage_percent(),
        'ram_usage_percent': _read_ram_usage_percent(),
        'temperatures_c': {
            'cpu': _read_cpu_temp_c(),
        },
        'timestamp': now_taiwan().isoformat()
    }


def init_db():
    """初始化資料庫"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            co2_ppm INTEGER,
            temperature_c REAL,
            humidity REAL,
            raw_data TEXT,
            rssi INTEGER,
            cpu_usage_percent REAL,
            ram_usage_percent REAL,
            cpu_temp_c REAL
        )
    """)
    existing_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(readings)").fetchall()
    }
    if "cpu_usage_percent" not in existing_cols:
        conn.execute("ALTER TABLE readings ADD COLUMN cpu_usage_percent REAL")
    if "ram_usage_percent" not in existing_cols:
        conn.execute("ALTER TABLE readings ADD COLUMN ram_usage_percent REAL")
    if "cpu_temp_c" not in existing_cols:
        conn.execute("ALTER TABLE readings ADD COLUMN cpu_temp_c REAL")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp ON readings(timestamp)
    """)
    conn.commit()
    conn.close()


def parse_co2_data(data):
    """解析 CO2 數據"""
    if len(data) >= 2:
        co2_value = struct.unpack('<H', data[:2])[0]
        if 300 <= co2_value <= 10000:
            return co2_value
    return None


def parse_temp_data(data):
    """解析溫度數據（從 4 bytes 特徵值）
    
    注意：這個特徵值可能包含其他數據，主要溫度數據來自 20 bytes 通知
    """
    if len(data) >= 4:
        # 嘗試多種格式
        try:
            # bytes 0-2 (big-endian, 除以100)
            temp_raw = struct.unpack('>H', data[0:2])[0]
            temp_c = temp_raw / 100.0
            if 0 <= temp_c <= 50:
                return temp_c
        except:
            pass
        
        try:
            # bytes 2-4 (big-endian, 除以100)
            temp_raw = struct.unpack('>H', data[2:4])[0]
            temp_c = temp_raw / 100.0
            if 0 <= temp_c <= 50:
                return temp_c
        except:
            pass
    
    return None


def save_reading(
    co2_ppm=None,
    temperature_c=None,
    humidity=None,
    raw_data=None,
    rssi=None,
    cpu_usage_percent=None,
    ram_usage_percent=None,
    cpu_temp_c=None
):
    """儲存讀數到資料庫"""
    conn = get_db()
    conn.execute("""
        INSERT INTO readings (
            timestamp, co2_ppm, temperature_c, humidity, raw_data, rssi,
            cpu_usage_percent, ram_usage_percent, cpu_temp_c
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now_taiwan().isoformat(),
        co2_ppm,
        temperature_c,
        humidity,
        raw_data,
        rssi,
        cpu_usage_percent,
        ram_usage_percent,
        cpu_temp_c
    ))
    conn.commit()
    conn.close()


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
            check_and_notify(co2_ppm=co2_ppm, temperature_c=temperature_c, humidity=humidity)
        except Exception as e:
            log_debug(f"Telegram 通知檢查失敗: {e}")
    
    # 透過 WebSocket 廣播給所有客戶端
    socketio.emit('sensor_update', latest_reading)


# ===== 已停用：其他解析方式（保留代碼） =====
def co2_notification_handler(sender, data):
    """處理 CO2 通知（已停用 - 僅使用 sensirion-ble）"""
    # 已停用：不再處理 CO2 通知
    # co2_value = parse_co2_data(data)
    # if co2_value:
    #     save_reading(co2_ppm=co2_value, raw_data=data.hex())
    #     update_latest_reading(co2_ppm=co2_value)
    pass


def temp_notification_handler(sender, data):
    """處理溫度通知（已停用 - 僅使用 sensirion-ble）"""
    # 已停用：不再處理溫度通知
    # temp_value = parse_temp_data(data)
    # if temp_value:
    #     save_reading(temperature_c=temp_value, raw_data=data.hex())
    #     update_latest_reading(temperature_c=temp_value)
    # else:
    #     # 調試：記錄無法解析的數據
    #     log_debug(f"溫度通知數據無法解析: {data.hex()} (長度: {len(data)})")
    pass


def parse_humidity_data(data):
    """解析濕度數據"""
    if len(data) >= 2:
        # 嘗試多種格式
        hum_le = struct.unpack('<H', data[0:2])[0]
        hum_be = struct.unpack('>H', data[0:2])[0]
        
        # 濕度通常 0-100%，可能以 0-10000 (除以100) 的形式存儲
        hum_value_le = hum_le / 100.0
        hum_value_be = hum_be / 100.0
        
        if 0 <= hum_value_le <= 100:
            return hum_value_le
        if 0 <= hum_value_be <= 100:
            return hum_value_be
    
    return None


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


def notification_handler_20bytes_original(sender, data):
    """處理 20 bytes 通知數據（原始解析方式 - 保留作為備份）
    
    根據實際數據分析，正確的數據結構：
    - bytes 0-2: 序號/計數器
    - bytes 2-4: 溫度 (little-endian, 除以1000) - 例如 26735 / 1000 = 26.735°C
    - bytes 4-6: 濕度 (little-endian, 除以1000) - 例如 33188 / 1000 = 33.188%
    - bytes 6-8: CO2 備份值（可能）
    - bytes 10-12: 溫度備份值（重複）
    - bytes 12-14: 濕度備份值（重複）
    - bytes 14-16: CO2 (little-endian) - 例如 1102 ppm
    """
    if len(data) != 20:
        return
    
    co2_value = None
    temp_value = None
    humidity_value = None
    
    # 解析 CO2: bytes 14-16 (little-endian) - 已確認正確
    if len(data) >= 16:
        co2_raw = struct.unpack('<H', data[14:16])[0]
        if 300 <= co2_raw <= 10000:
            co2_value = co2_raw
    
    # 解析溫度: bytes 2-4 (little-endian, 除以1000)
    if len(data) >= 4:
        temp_raw = struct.unpack('<H', data[2:4])[0]
        temp_c = temp_raw / 1000.0
        if 0 <= temp_c <= 50:
            temp_value = temp_c
    
    # 解析濕度: bytes 4-6 (little-endian, 除以1000)
    if len(data) >= 6:
        hum_raw = struct.unpack('<H', data[4:6])[0]
        hum_value = hum_raw / 1000.0
        if 0 <= hum_value <= 100:
            humidity_value = hum_value
    
    return {
        'co2_ppm': co2_value,
        'temperature_c': temp_value,
        'humidity': humidity_value
    }


def notification_handler_20bytes(sender, data):
    """處理 20 bytes 通知數據（已停用 - 僅使用 sensirion-ble）"""
    # 已停用：不再處理 20 bytes 通知數據
    # if len(data) != 20:
    #     return
    # 
    # # 優先嘗試使用 sensirion-ble 解析（從廣告數據）
    # # 但 20 bytes 通知數據可能不是標準的廣告格式
    # # 所以我們主要使用原始解析方式
    # 
    # # 使用原始解析方式
    # result = notification_handler_20bytes_original(sender, data)
    # 
    # if result and (result.get('co2_ppm') or result.get('temperature_c') or result.get('humidity')):
    #     save_reading(
    #         co2_ppm=result.get('co2_ppm'),
    #         temperature_c=result.get('temperature_c'),
    #         humidity=result.get('humidity'),
    #         raw_data=data.hex()
    #     )
    #     update_latest_reading(
    #         co2_ppm=result.get('co2_ppm'),
    #         temperature_c=result.get('temperature_c'),
    #         humidity=result.get('humidity')
    #     )
    pass


async def monitor_myco2_async():
    """異步監控 MyCO2"""
    global monitoring_active
    
    while monitoring_active:
        try:
            # 尋找設備
            devices = await BleakScanner.discover(timeout=5)
            
            myco2_device = None
            rssi = -100
            manufacturer_data = {}
            for device in devices:
                if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
                    myco2_device = device
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
            
            # ===== 已停用：連接設備和通知訂閱（保留代碼） =====
            # 現在只使用 sensirion-ble 解析廣告數據，不需要連接設備
            # if not myco2_device:
            #     await asyncio.sleep(5)
            #     continue
            # 
            # # 連接設備
            # try:
            #     async with BleakClient(myco2_device.address, timeout=10.0) as client:
            #         update_latest_reading(rssi=rssi)
            #         
            #         # 等待服務解析
            #         await asyncio.sleep(2)
            #         
            #         # 讀取 CO2
            #         try:
            #             co2_data = await client.read_gatt_char(CO2_CHAR_UUID)
            #             co2_value = parse_co2_data(co2_data)
            #             if co2_value:
            #                 save_reading(co2_ppm=co2_value, raw_data=co2_data.hex(), rssi=rssi)
            #                 update_latest_reading(co2_ppm=co2_value, rssi=rssi)
            #         except Exception:
            #             pass
            #         
            #         # 讀取溫度（這個特徵值可能同時包含CO2和溫度）
            #         try:
            #             temp_data = await client.read_gatt_char(TEMP_CHAR_UUID)
            #             log_debug(f"讀取到溫度特徵值數據: {temp_data.hex()} (長度: {len(temp_data)})")
            #             temp_value = parse_temp_data(temp_data)
            #             if temp_value:
            #                 log_debug(f"成功解析溫度: {temp_value}°C")
            #                 save_reading(temperature_c=temp_value, raw_data=temp_data.hex(), rssi=rssi)
            #                 update_latest_reading(temperature_c=temp_value)
            #             else:
            #                 # 如果解析失敗，記錄原始數據以便調試
            #                 log_debug(f"溫度數據解析失敗: {temp_data.hex()} (長度: {len(temp_data)})")
            #                 # 嘗試所有可能的解析方式
            #                 if len(temp_data) >= 4:
            #                     val1 = struct.unpack('>H', temp_data[0:2])[0]
            #                     val2 = struct.unpack('>H', temp_data[2:4])[0]
            #                     log_debug(f"  bytes 0-2 (big-endian): {val1} = {val1/100.0:.2f}°C")
            #                     log_debug(f"  bytes 2-4 (big-endian): {val2} = {val2/100.0:.2f}°C")
            #         except Exception as e:
            #             log_debug(f"讀取溫度失敗: {e}")
            #         
            #         # 訂閱通知
            #         try:
            #             await client.start_notify(CO2_CHAR_UUID, co2_notification_handler)
            #             log_debug("已訂閱 CO2 通知")
            #         except Exception as e:
            #             log_debug(f"訂閱 CO2 通知失敗: {e}")
            #         
            #         try:
            #             await client.start_notify(TEMP_CHAR_UUID, temp_notification_handler)
            #             log_debug("已訂閱溫度通知")
            #         except Exception as e:
            #             log_debug(f"訂閱溫度通知失敗: {e}")
            #         
            #         # 訂閱 20 bytes 通知數據（包含多個感測器讀數）
            #         try:
            #             await client.start_notify(NOTIFY_CHAR_UUID, notification_handler_20bytes)
            #             log_debug("已訂閱 20 bytes 通知數據")
            #         except Exception as e:
            #             log_debug(f"訂閱 20 bytes 通知失敗: {e}")
            #         
            #         # 保持連接並定期讀取（每30秒讀取一次）
            #         read_count = 0
            #         while monitoring_active and client.is_connected:
            #             await asyncio.sleep(1)
            #             read_count += 1
            #             
            #             # 每30秒主動讀取一次數據（作為通知的備份）
            #             if read_count >= 30:
            #                 read_count = 0
            #                 try:
            #                     # 讀取 CO2
            #                     co2_data = await client.read_gatt_char(CO2_CHAR_UUID)
            #                     co2_value = parse_co2_data(co2_data)
            #                     if co2_value:
            #                         save_reading(co2_ppm=co2_value, raw_data=co2_data.hex(), rssi=rssi)
            #                         update_latest_reading(co2_ppm=co2_value, rssi=rssi)
            #                 except Exception:
            #                     pass
            #                 
            #                 try:
            #                     # 讀取溫度
            #                     temp_data = await client.read_gatt_char(TEMP_CHAR_UUID)
            #                     temp_value = parse_temp_data(temp_data)
            #                     if temp_value:
            #                         save_reading(temperature_c=temp_value, raw_data=temp_data.hex(), rssi=rssi)
            #                         update_latest_reading(temperature_c=temp_value)
            #                 except Exception:
            #                     pass
            #                 
            # except Exception:
            #     await asyncio.sleep(5)
            
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
    hours = int(request.args.get('hours', 24))
    max_points = int(request.args.get('max_points', 0))
    since = now_taiwan() - timedelta(hours=hours)
    
    conn = get_db()
    rows = conn.execute("""
        SELECT
            timestamp, co2_ppm, temperature_c, humidity, rssi,
            cpu_usage_percent, ram_usage_percent, cpu_temp_c
        FROM readings
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    """, (since.isoformat(),)).fetchall()
    conn.close()
    
    data = [dict(row) for row in rows]
    if max_points > 0 and len(data) > max_points:
        step = len(data) / max_points
        sampled = []
        for i in range(max_points):
            idx = int(i * step)
            sampled.append(data[min(idx, len(data) - 1)])
        data = sampled
    return jsonify(data)


@app.route('/api/stats')
def api_stats():
    """獲取統計數據"""
    conn = get_db()
    
    # 最近24小時的統計
    since = now_taiwan() - timedelta(hours=24)
    
    stats = conn.execute("""
        SELECT 
            COUNT(*) as count,
            AVG(co2_ppm) as avg_co2,
            MIN(co2_ppm) as min_co2,
            MAX(co2_ppm) as max_co2,
            AVG(temperature_c) as avg_temp,
            MIN(temperature_c) as min_temp,
            MAX(temperature_c) as max_temp
        FROM readings
        WHERE timestamp >= ?
    """, (since.isoformat(),)).fetchone()
    
    conn.close()
    
    return jsonify(dict(stats))


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
    init_db()
    
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
