#!/usr/bin/env python3
"""掃描並連接 MyCO2 CO2 感測器設備"""

import asyncio
import sys
from datetime import datetime
from bleak import BleakScanner, BleakClient

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"

async def scan_devices(duration=10):
    """掃描藍牙設備"""
    print(f"開始掃描藍牙設備（持續 {duration} 秒）...")
    print(f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    devices = await BleakScanner.discover(timeout=duration)
    
    print("=" * 70)
    print("發現的藍牙設備：")
    print("=" * 70)
    
    myco2_found = False
    for device in devices:
        name = device.name or "Unknown"
        mac = device.address
        rssi = device.rssi if hasattr(device, 'rssi') else "N/A"
        
        print(f"名稱: {name}")
        print(f"MAC:  {mac}")
        print(f"RSSI: {rssi} dBm")
        
        # 顯示廣告數據（如果可用）
        try:
            if hasattr(device, 'details'):
                details = device.details
                if 'props' in details:
                    props = details['props']
                    # 顯示 RSSI
                    if 'RSSI' in props:
                        print(f"RSSI: {props['RSSI']} dBm")
                    # 解析製造商數據
                    if 'ManufacturerData' in props:
                        mfg_data = props['ManufacturerData']
                        for mfg_id, data in mfg_data.items():
                            print(f"製造商 ID: 0x{mfg_id:04x}")
                            print(f"製造商數據: {data.hex()}")
                            # 如果是 MyCO2 (0x06d5 = 1749)
                            if mfg_id == 0x06d5:
                                from parse_myco2 import parse_myco2_manufacturer_data
                                parsed = parse_myco2_manufacturer_data(data)
                                if parsed:
                                    print("解析的感測器數據:")
                                    if 'co2_ppm' in parsed:
                                        print(f"  CO2: {parsed['co2_ppm']} ppm")
                                    if 'temperature_c' in parsed:
                                        print(f"  溫度: {parsed['temperature_c']:.2f}°C")
                                    if 'humidity_percent' in parsed:
                                        print(f"  濕度: {parsed['humidity_percent']:.2f}%")
        except Exception as e:
            print(f"解析廣告數據時出錯: {e}")
        
        if MYCO2_NAME.lower() in name.lower() or mac.upper() == MYCO2_MAC.upper():
            myco2_found = True
            print(">>> 這是 MyCO2 設備！")
        
        print("-" * 70)
    
    print(f"\n總共發現 {len(devices)} 個設備")
    if myco2_found:
        print(f"✓ 找到 MyCO2 設備")
    else:
        print(f"✗ 未找到 MyCO2 設備")
    
    return myco2_found, devices


async def connect_myco2(mac_address):
    """連接 MyCO2 設備並讀取特徵值"""
    print(f"\n嘗試連接 MyCO2 ({mac_address})...")
    
    try:
        async with BleakClient(mac_address, timeout=10.0) as client:
            print(f"✓ 已連接到 {mac_address}")
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
                    print(f"  特徵值 UUID: {char.uuid}")
                    print(f"    描述: {char.description}")
                    print(f"    屬性: {char.properties}")
                    
                    # 嘗試讀取可讀的特徵值
                    if "read" in char.properties:
                        try:
                            value = await client.read_gatt_char(char.uuid)
                            print(f"    值: {value.hex() if value else 'None'}")
                            if value:
                                try:
                                    # 嘗試解析為數字
                                    if len(value) >= 2:
                                        # 可能是 CO2 值（2 bytes, big-endian）
                                        co2_value = int.from_bytes(value[:2], byteorder='big')
                                        print(f"    解析為數字: {co2_value}")
                                except:
                                    pass
                        except Exception as e:
                            print(f"    讀取失敗: {e}")
                    
                    print()
            
            # 訂閱通知（如果有）
            print("\n嘗試訂閱通知...")
            for service in services:
                for char in service.characteristics:
                    if "notify" in char.properties or "indicate" in char.properties:
                        try:
                            await client.start_notify(char.uuid, notification_handler)
                            print(f"✓ 已訂閱 {char.uuid}")
                        except Exception as e:
                            print(f"✗ 訂閱 {char.uuid} 失敗: {e}")
            
            # 保持連接一段時間以接收通知
            print("\n監聽數據（10秒）...")
            await asyncio.sleep(10)
            
    except Exception as e:
        print(f"✗ 連接失敗: {e}")
        return False
    
    return True


def notification_handler(sender, data):
    """處理 BLE 通知數據"""
    print(f"\n[通知] 來自 {sender}:")
    print(f"  原始數據: {data.hex()}")
    
    # 嘗試解析 CO2 值
    if len(data) >= 2:
        try:
            # 常見的 CO2 感測器數據格式
            co2_value = int.from_bytes(data[:2], byteorder='big')
            print(f"  解析為 CO2: {co2_value} ppm")
        except:
            pass
        
        if len(data) >= 4:
            try:
                # 可能是多個值
                value1 = int.from_bytes(data[0:2], byteorder='big')
                value2 = int.from_bytes(data[2:4], byteorder='big')
                print(f"  值1: {value1}, 值2: {value2}")
            except:
                pass


async def main():
    """主函數"""
    print("=" * 70)
    print("MyCO2 CO2 感測器掃描工具")
    print("=" * 70)
    
    # 掃描設備
    myco2_found, devices = await scan_devices(duration=10)
    
    if not myco2_found:
        print("\n未找到 MyCO2 設備，請確認設備已開啟並在範圍內")
        return
    
    # 找到 MyCO2，嘗試連接
    myco2_device = None
    for device in devices:
        if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
            myco2_device = device
            break
    
    if myco2_device:
        await connect_myco2(myco2_device.address)
    else:
        # 使用已知的 MAC 地址嘗試連接
        print(f"\n使用已知 MAC 地址嘗試連接: {MYCO2_MAC}")
        await connect_myco2(MYCO2_MAC)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n掃描已取消")
    except Exception as e:
        print(f"\n錯誤: {e}")
        import traceback
        traceback.print_exc()
