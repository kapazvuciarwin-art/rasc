#!/usr/bin/env python3
"""持續監控 MyCO2 CO2 感測器"""

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from bleak import BleakScanner, BleakClient

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"
DATABASE = "myco2_data.db"

def init_db():
    """初始化資料庫"""
    conn = sqlite3.connect(DATABASE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            co2_value INTEGER,
            temperature REAL,
            humidity REAL,
            raw_data TEXT,
            rssi INTEGER
        )
    """)
    conn.commit()
    conn.close()


def save_reading(co2_value=None, temperature=None, humidity=None, raw_data=None, rssi=None):
    """儲存讀數到資料庫"""
    conn = sqlite3.connect(DATABASE)
    conn.execute("""
        INSERT INTO readings (timestamp, co2_value, temperature, humidity, raw_data, rssi)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        co2_value,
        temperature,
        humidity,
        raw_data,
        rssi
    ))
    conn.commit()
    conn.close()


def notification_handler(sender, data):
    """處理 BLE 通知數據"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{timestamp}] 收到數據:")
    print(f"  來源: {sender}")
    print(f"  原始: {data.hex()}")
    
    co2_value = None
    temperature = None
    humidity = None
    
    # 嘗試解析數據
    if len(data) >= 2:
        # 常見格式：CO2 值（2 bytes, big-endian）
        co2_value = int.from_bytes(data[:2], byteorder='big')
        print(f"  CO2: {co2_value} ppm")
    
    if len(data) >= 4:
        # 可能包含溫度和濕度
        try:
            temp_raw = int.from_bytes(data[2:4], byteorder='big')
            temperature = temp_raw / 100.0  # 假設格式為 *100
            print(f"  溫度: {temperature}°C")
        except:
            pass
    
    if len(data) >= 6:
        try:
            hum_raw = int.from_bytes(data[4:6], byteorder='big')
            humidity = hum_raw / 100.0
            print(f"  濕度: {humidity}%")
        except:
            pass
    
    # 儲存到資料庫
    save_reading(
        co2_value=co2_value,
        temperature=temperature,
        humidity=humidity,
        raw_data=data.hex(),
        rssi=None
    )


async def find_myco2():
    """尋找 MyCO2 設備"""
    print("掃描 MyCO2 設備...")
    devices = await BleakScanner.discover(timeout=5)
    
    for device in devices:
        if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
            return device
    
    return None


async def monitor_myco2():
    """監控 MyCO2 設備"""
    print("=" * 70)
    print("MyCO2 持續監控")
    print("=" * 70)
    
    init_db()
    
    while True:
        try:
            # 尋找設備
            device = await find_myco2()
            
            if not device:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 未找到 MyCO2，5秒後重試...")
                await asyncio.sleep(5)
                continue
            
            print(f"\n找到 MyCO2: {device.address} (RSSI: {device.rssi if hasattr(device, 'rssi') else 'N/A'})")
            
            # 連接設備
            try:
                async with BleakClient(device.address, timeout=10.0) as client:
                    print(f"✓ 已連接")
                    
                    # 獲取服務和特徵值
                    await asyncio.sleep(2)  # 等待服務解析
                    services = client.services
                    
                    # 訂閱所有可通知的特徵值
                    subscribed = False
                    for service in services:
                        for char in service.characteristics:
                            if "notify" in char.properties or "indicate" in char.properties:
                                try:
                                    await client.start_notify(char.uuid, notification_handler)
                                    print(f"✓ 已訂閱 {char.uuid}")
                                    subscribed = True
                                except Exception as e:
                                    print(f"✗ 訂閱失敗 {char.uuid}: {e}")
                            
                            # 也嘗試讀取可讀的特徵值
                            if "read" in char.properties:
                                try:
                                    value = await client.read_gatt_char(char.uuid)
                                    print(f"讀取 {char.uuid}: {value.hex()}")
                                    notification_handler(char.uuid, value)
                                except Exception as e:
                                    pass
                    
                    if subscribed:
                        print("\n開始監聽數據...")
                        # 持續監聽
                        while client.is_connected:
                            await asyncio.sleep(1)
                    else:
                        print("未找到可訂閱的特徵值，嘗試定期讀取...")
                        # 定期讀取
                        for _ in range(60):  # 讀取 60 次（約 1 分鐘）
                            for service in services:
                                for char in service.characteristics:
                                    if "read" in char.properties:
                                        try:
                                            value = await client.read_gatt_char(char.uuid)
                                            notification_handler(char.uuid, value)
                                        except:
                                            pass
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
