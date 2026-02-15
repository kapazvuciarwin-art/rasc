#!/usr/bin/env python3
"""簡化的 MyCO2 監控腳本 - 讀取 CO2 和溫度數據"""

import asyncio
import sqlite3
import struct
from datetime import datetime
from bleak import BleakScanner, BleakClient

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"
DATABASE = "myco2_data.db"

# 關鍵特徵值 UUID
CO2_CHAR_UUID = "00007001-b38d-4985-720e-0f993a68ee41"  # CO2 讀數
TEMP_CHAR_UUID = "00007003-b38d-4985-720e-0f993a68ee41"  # 可能包含溫度

def init_db():
    """初始化資料庫"""
    conn = sqlite3.connect(DATABASE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            co2_ppm INTEGER,
            temperature_c REAL,
            raw_data TEXT,
            rssi INTEGER
        )
    """)
    conn.commit()
    conn.close()


def save_reading(co2_ppm=None, temperature_c=None, raw_data=None, rssi=None):
    """儲存讀數到資料庫"""
    conn = sqlite3.connect(DATABASE)
    conn.execute("""
        INSERT INTO readings (timestamp, co2_ppm, temperature_c, raw_data, rssi)
        VALUES (?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        co2_ppm,
        temperature_c,
        raw_data,
        rssi
    ))
    conn.commit()
    conn.close()


def parse_co2_data(data):
    """解析 CO2 數據（2 bytes, little-endian）"""
    if len(data) >= 2:
        co2_value = struct.unpack('<H', data[:2])[0]
        if 300 <= co2_value <= 10000:
            return co2_value
    return None


def parse_temp_data(data):
    """解析溫度數據（從 4 bytes 數據中）"""
    if len(data) >= 4:
        # 嘗試多種格式
        # 格式1: bytes 2-4 可能是溫度 (little-endian, 除以100)
        temp_raw = struct.unpack('<H', data[2:4])[0]
        temp_c = temp_raw / 100.0
        if 0 <= temp_c <= 50:
            return temp_c
        
        # 格式2: bytes 0-2 可能是溫度
        temp_raw = struct.unpack('<H', data[0:2])[0]
        temp_c = temp_raw / 100.0
        if 0 <= temp_c <= 50:
            return temp_c
    return None


def co2_notification_handler(sender, data):
    """處理 CO2 通知"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    co2_value = parse_co2_data(data)
    
    if co2_value:
        print(f"[{timestamp}] CO2: {co2_value} ppm")
        save_reading(co2_ppm=co2_value, raw_data=data.hex())
    else:
        print(f"[{timestamp}] CO2 通知: {data.hex()} (無法解析)")


def temp_notification_handler(sender, data):
    """處理溫度通知"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    temp_value = parse_temp_data(data)
    
    if temp_value:
        print(f"[{timestamp}] 溫度: {temp_value:.2f}°C")
        save_reading(temperature_c=temp_value, raw_data=data.hex())
    else:
        print(f"[{timestamp}] 溫度通知: {data.hex()} (無法解析)")


async def monitor_myco2():
    """監控 MyCO2 設備"""
    print("=" * 70)
    print("MyCO2 簡化監控工具")
    print("=" * 70)
    
    init_db()
    
    while True:
        try:
            # 尋找設備
            print("\n掃描 MyCO2 設備...")
            devices = await BleakScanner.discover(timeout=5)
            
            myco2_device = None
            for device in devices:
                if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
                    myco2_device = device
                    rssi = -100
                    if hasattr(device, 'details') and 'props' in device.details:
                        props = device.details['props']
                        rssi = props.get('RSSI', -100)
                    print(f"✓ 找到 MyCO2: {device.address} (RSSI: {rssi} dBm)")
                    break
            
            if not myco2_device:
                print("✗ 未找到 MyCO2，5秒後重試...")
                await asyncio.sleep(5)
                continue
            
            # 連接設備
            print(f"連接設備 {myco2_device.address}...")
            try:
                async with BleakClient(myco2_device.address, timeout=10.0) as client:
                    print("✓ 已連接")
                    
                    # 等待服務解析
                    await asyncio.sleep(2)
                    
                    # 讀取 CO2 特徵值
                    try:
                        co2_data = await client.read_gatt_char(CO2_CHAR_UUID)
                        co2_value = parse_co2_data(co2_data)
                        if co2_value:
                            print(f"✓ 當前 CO2: {co2_value} ppm")
                            save_reading(co2_ppm=co2_value, raw_data=co2_data.hex(), rssi=rssi)
                    except Exception as e:
                        print(f"✗ 讀取 CO2 失敗: {e}")
                    
                    # 讀取溫度特徵值（如果存在）
                    try:
                        temp_data = await client.read_gatt_char(TEMP_CHAR_UUID)
                        temp_value = parse_temp_data(temp_data)
                        if temp_value:
                            print(f"✓ 當前溫度: {temp_value:.2f}°C")
                            save_reading(temperature_c=temp_value, raw_data=temp_data.hex())
                    except Exception as e:
                        pass  # 溫度特徵值可能不存在
                    
                    # 訂閱 CO2 通知
                    try:
                        await client.start_notify(CO2_CHAR_UUID, co2_notification_handler)
                        print(f"✓ 已訂閱 CO2 通知 ({CO2_CHAR_UUID})")
                    except Exception as e:
                        print(f"✗ 訂閱 CO2 通知失敗: {e}")
                    
                    # 訂閱溫度通知（如果存在）
                    try:
                        await client.start_notify(TEMP_CHAR_UUID, temp_notification_handler)
                        print(f"✓ 已訂閱溫度通知 ({TEMP_CHAR_UUID})")
                    except Exception as e:
                        pass
                    
                    # 持續監聽
                    print("\n開始監聽數據（按 Ctrl+C 停止）...")
                    print("=" * 70)
                    
                    while client.is_connected:
                        await asyncio.sleep(1)
                        
            except Exception as e:
                print(f"✗ 連接錯誤: {e}")
                print("5秒後重試...")
                await asyncio.sleep(5)
                
        except KeyboardInterrupt:
            print("\n\n監控已停止")
            break
        except Exception as e:
            print(f"錯誤: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(monitor_myco2())
    except KeyboardInterrupt:
        print("\n程式已結束")
