#!/usr/bin/env python3
"""連接 MyCO2 設備並讀取完整的感測器數據"""

import asyncio
import struct
from datetime import datetime
from bleak import BleakScanner, BleakClient

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"

# 常見的環境感測器 UUID
ENVIRONMENTAL_SENSING_SERVICE = "0000181a-0000-1000-8000-00805f9b34fb"
CO2_CHARACTERISTIC = "00002bdc-0000-1000-8000-00805f9b34fb"  # CO2 Concentration
TEMPERATURE_CHAR = "00002a6e-0000-1000-8000-00805f9b34fb"  # Temperature
HUMIDITY_CHAR = "00002a6f-0000-1000-8000-00805f9b34fb"  # Humidity

# 通用特徵值
GENERIC_READ_CHAR = "0000fff1-0000-1000-8000-00805f9b34fb"
GENERIC_NOTIFY_CHAR = "0000fff2-0000-1000-8000-00805f9b34fb"


def parse_sensor_data(uuid, data):
    """根據 UUID 解析感測器數據"""
    result = {'uuid': str(uuid), 'raw': data.hex(), 'length': len(data)}
    
    # 特徵值 00007001 的格式：2 bytes, little-endian CO2 值
    if '00007001' in str(uuid):
        if len(data) >= 2:
            co2_value = struct.unpack('<H', data[:2])[0]
            if 300 <= co2_value <= 10000:
                result['co2_ppm'] = co2_value
                return result
    
    # 特徵值 00008004 的通知數據格式：20 bytes
    # 格式: [序號(1)] [未知(1)] [CO2(2)] [溫度(2)] [其他(2)] [CO2(2)] [溫度(2)] [其他(2)] [填充(6)]
    if '00008004' in str(uuid) and len(data) == 20:
        result['sequence'] = data[0]
        
        # 第一個讀數組 (字節 2-8)
        if len(data) >= 9:
            co2_1 = struct.unpack('<H', data[2:4])[0]
            temp_1_raw = struct.unpack('<H', data[4:6])[0]
            temp_1 = temp_1_raw / 100.0
            
            # 檢查合理性
            if 300 <= co2_1 <= 10000:
                result['co2_ppm'] = co2_1
            if 0 <= temp_1 <= 50:
                result['temperature_c'] = temp_1
        
        # 第二個讀數組 (字節 10-16)
        if len(data) >= 17:
            co2_2 = struct.unpack('<H', data[10:12])[0]
            temp_2_raw = struct.unpack('<H', data[12:14])[0]
            temp_2 = temp_2_raw / 100.0
            
            # 如果第一個讀數不合理，使用第二個
            if 'co2_ppm' not in result and 300 <= co2_2 <= 10000:
                result['co2_ppm'] = co2_2
            if 'temperature_c' not in result and 0 <= temp_2 <= 50:
                result['temperature_c'] = temp_2
        
        return result
    
    # 通用解析：2 bytes
    if len(data) >= 2:
        value_be = struct.unpack('>H', data[:2])[0]
        value_le = struct.unpack('<H', data[:2])[0]
        
        # CO2 通常範圍 400-5000 ppm
        if 300 <= value_be <= 10000:
            result['co2_ppm'] = value_be
        elif 300 <= value_le <= 10000:
            result['co2_ppm'] = value_le
        
        # 溫度通常範圍 0-50°C，以 0.01 為單位
        if 0 <= value_be <= 5000:
            result['temperature_c'] = value_be / 100.0
        elif 0 <= value_le <= 5000:
            result['temperature_c'] = value_le / 100.0
    
    return result


def notification_handler(sender, data):
    """處理 BLE 通知"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"\n[{timestamp}] 通知來自 {sender}:")
    print(f"  原始數據: {data.hex()}")
    
    parsed = parse_sensor_data(sender, data)
    
    if 'co2_ppm' in parsed:
        print(f"  ✓ CO2: {parsed['co2_ppm']} ppm")
    if 'temperature_c' in parsed:
        print(f"  ✓ 溫度: {parsed['temperature_c']:.2f}°C")
    
    # 顯示所有可能的解析
    print(f"  解析詳情: {parsed}")


async def find_and_connect_myco2():
    """尋找並連接 MyCO2"""
    print("=" * 70)
    print("MyCO2 設備連接工具")
    print("=" * 70)
    
    # 掃描設備
    print("\n掃描 MyCO2 設備...")
    devices = await BleakScanner.discover(timeout=5)
    
    myco2_device = None
    for device in devices:
        if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
            myco2_device = device
            print(f"✓ 找到 MyCO2: {device.address}")
            if hasattr(device, 'details') and 'props' in device.details:
                props = device.details['props']
                if 'RSSI' in props:
                    print(f"  RSSI: {props['RSSI']} dBm")
                if 'ManufacturerData' in props:
                    mfg_data = props['ManufacturerData']
                    for mfg_id, data in mfg_data.items():
                        if mfg_id == 0x06d5:
                            print(f"  廣告數據: {data.hex()}")
            break
    
    if not myco2_device:
        print(f"✗ 未找到 MyCO2，嘗試使用已知 MAC: {MYCO2_MAC}")
        myco2_device = type('Device', (), {'address': MYCO2_MAC})()
    
    # 連接設備
    print(f"\n連接設備 {myco2_device.address}...")
    try:
        async with BleakClient(myco2_device.address, timeout=15.0) as client:
            print(f"✓ 已連接")
            print(f"  連接狀態: {client.is_connected}")
            
            # 獲取所有服務
            print("\n發現的服務和特徵值：")
            print("=" * 70)
            
            # 等待服務解析完成
            await asyncio.sleep(2)
            
            services = client.services
            for service in services:
                print(f"\n服務 UUID: {service.uuid}")
                print(f"  描述: {service.description}")
                
                for char in service.characteristics:
                    print(f"\n  特徵值 UUID: {char.uuid}")
                    print(f"    描述: {char.description}")
                    print(f"    屬性: {char.properties}")
                    
                    # 讀取可讀的特徵值
                    if "read" in char.properties:
                        try:
                            value = await client.read_gatt_char(char.uuid)
                            print(f"    讀取值: {value.hex()}")
                            
                            parsed = parse_sensor_data(char.uuid, value)
                            if 'co2_ppm' in parsed:
                                print(f"    → CO2: {parsed['co2_ppm']} ppm")
                            if 'temperature_c' in parsed:
                                print(f"    → 溫度: {parsed['temperature_c']:.2f}°C")
                            
                            # 顯示完整解析
                            print(f"    完整解析: {parsed}")
                        except Exception as e:
                            print(f"    讀取失敗: {e}")
                    
                    # 訂閱通知
                    if "notify" in char.properties or "indicate" in char.properties:
                        try:
                            await client.start_notify(char.uuid, notification_handler)
                            print(f"    ✓ 已訂閱通知")
                        except Exception as e:
                            print(f"    訂閱失敗: {e}")
            
            # 保持連接並監聽
            print("\n" + "=" * 70)
            print("開始監聽數據（30秒）...")
            print("=" * 70)
            await asyncio.sleep(30)
            
    except Exception as e:
        print(f"✗ 連接失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(find_and_connect_myco2())
    except KeyboardInterrupt:
        print("\n\n程式已結束")
