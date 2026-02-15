#!/usr/bin/env python3
"""測試使用 sensirion-ble 庫解析 MyCO2 數據"""

import asyncio
from bleak import BleakScanner, BleakClient
from sensirion_ble import SensirionDevice

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"

async def test_sensirion_ble():
    """測試 sensirion-ble 庫"""
    print("=" * 70)
    print("測試 sensirion-ble 庫解析 MyCO2")
    print("=" * 70)
    
    # 掃描設備
    print("\n掃描 MyCO2 設備...")
    devices = await BleakScanner.discover(timeout=5)
    
    myco2_device = None
    for device in devices:
        if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
            myco2_device = device
            print(f"✓ 找到 MyCO2: {device.address}")
            break
    
    if not myco2_device:
        print("✗ 未找到 MyCO2")
        return
    
    # 連接設備
    print(f"\n連接設備...")
    try:
        async with BleakClient(myco2_device.address, timeout=15.0) as client:
            print("✓ 已連接")
            
            await asyncio.sleep(2)
            
            # 嘗試使用 sensirion-ble 解析
            try:
                print("\n嘗試使用 sensirion-ble 解析...")
                
                # 獲取所有服務和特徵值
                services = client.services
                
                # 尋找可能的 Sensirion 特徵值
                for service in services:
                    for char in service.characteristics:
                        if "read" in char.properties:
                            try:
                                value = await client.read_gatt_char(char.uuid)
                                print(f"\n特徵值: {char.uuid}")
                                print(f"  原始數據: {value.hex()}")
                                
                                # 嘗試使用 sensirion-ble 解析
                                try:
                                    # 檢查是否有 SensirionDevice 類
                                    device = SensirionDevice(client, char.uuid)
                                    parsed = device.parse(value)
                                    print(f"  sensirion-ble 解析結果: {parsed}")
                                except Exception as e:
                                    print(f"  sensirion-ble 解析失敗: {e}")
                                    
                            except Exception as e:
                                pass
                
            except Exception as e:
                print(f"使用 sensirion-ble 時出錯: {e}")
                import traceback
                traceback.print_exc()
            
            # 也嘗試直接使用 sensirion-ble 的掃描功能
            print("\n嘗試使用 sensirion-ble 掃描...")
            try:
                # 檢查是否有掃描功能
                from sensirion_ble import scan_sensirion_devices
                sensirion_devices = await scan_sensirion_devices(timeout=5)
                print(f"找到 {len(sensirion_devices)} 個 Sensirion 設備")
                for dev in sensirion_devices:
                    print(f"  {dev}")
            except Exception as e:
                print(f"掃描失敗: {e}")
            
    except Exception as e:
        print(f"✗ 連接失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(test_sensirion_ble())
    except KeyboardInterrupt:
        print("\n測試已取消")
