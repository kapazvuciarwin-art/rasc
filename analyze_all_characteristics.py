#!/usr/bin/env python3
"""分析 MyCO2 所有特徵值的數據格式，找出濕度數據"""

import asyncio
import struct
from bleak import BleakScanner, BleakClient

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"

def parse_value(data, name="值"):
    """嘗試多種方式解析數據"""
    results = []
    
    if len(data) >= 2:
        val_le = struct.unpack('<H', data[0:2])[0]
        val_be = struct.unpack('>H', data[0:2])[0]
        results.append(f"{name} (2 bytes LE): {val_le} = {val_le/100.0:.2f}")
        results.append(f"{name} (2 bytes BE): {val_be} = {val_be/100.0:.2f}")
    
    if len(data) >= 4:
        val1_le = struct.unpack('<H', data[0:2])[0]
        val1_be = struct.unpack('>H', data[0:2])[0]
        val2_le = struct.unpack('<H', data[2:4])[0]
        val2_be = struct.unpack('>H', data[2:4])[0]
        results.append(f"{name}1 (bytes 0-2 LE): {val1_le} = {val1_le/100.0:.2f}")
        results.append(f"{name}1 (bytes 0-2 BE): {val1_be} = {val1_be/100.0:.2f}")
        results.append(f"{name}2 (bytes 2-4 LE): {val2_le} = {val2_le/100.0:.2f}")
        results.append(f"{name}2 (bytes 2-4 BE): {val2_be} = {val2_be/100.0:.2f}")
    
    if len(data) >= 6:
        val3_le = struct.unpack('<H', data[4:6])[0]
        val3_be = struct.unpack('>H', data[4:6])[0]
        results.append(f"{name}3 (bytes 4-6 LE): {val3_le} = {val3_le/100.0:.2f}")
        results.append(f"{name}3 (bytes 4-6 BE): {val3_be} = {val3_be/100.0:.2f}")
    
    return results


async def analyze_all_characteristics():
    """分析所有特徵值"""
    print("=" * 70)
    print("MyCO2 完整特徵值分析 - 尋找濕度數據")
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
            print("✓ 已連接\n")
            
            await asyncio.sleep(2)
            services = client.services
            
            all_readings = {}
            
            for service in services:
                print(f"\n{'='*70}")
                print(f"服務: {service.uuid}")
                print(f"描述: {service.description}")
                print(f"{'='*70}")
                
                for char in service.characteristics:
                    print(f"\n特徵值: {char.uuid}")
                    print(f"  描述: {char.description}")
                    print(f"  屬性: {char.properties}")
                    
                    # 讀取可讀的特徵值
                    if "read" in char.properties:
                        try:
                            value = await client.read_gatt_char(char.uuid)
                            hex_value = value.hex()
                            print(f"  讀取值: {hex_value}")
                            print(f"  長度: {len(value)} bytes")
                            
                            # 保存讀數
                            all_readings[char.uuid] = {
                                'service': service.uuid,
                                'description': char.description,
                                'data': value,
                                'hex': hex_value
                            }
                            
                            # 嘗試解析
                            if len(value) >= 2:
                                print(f"\n  解析嘗試:")
                                parsed = parse_value(value, "值")
                                for p in parsed[:6]:  # 只顯示前6種
                                    print(f"    {p}")
                                
                                # 檢查是否可能是濕度（通常 0-100%）
                                if len(value) >= 2:
                                    val_le = struct.unpack('<H', value[0:2])[0]
                                    val_be = struct.unpack('>H', value[0:2])[0]
                                    
                                    # 濕度通常在 0-100 範圍，或 0-10000 (除以100)
                                    if 0 <= val_le <= 10000:
                                        humidity_le = val_le / 100.0
                                        if 0 <= humidity_le <= 100:
                                            print(f"    ⭐ 可能是濕度 (LE): {humidity_le:.2f}%")
                                    
                                    if 0 <= val_be <= 10000:
                                        humidity_be = val_be / 100.0
                                        if 0 <= humidity_be <= 100:
                                            print(f"    ⭐ 可能是濕度 (BE): {humidity_be:.2f}%")
                                
                                # 如果是4 bytes，檢查第二個值
                                if len(value) >= 4:
                                    val2_le = struct.unpack('<H', value[2:4])[0]
                                    val2_be = struct.unpack('>H', value[2:4])[0]
                                    
                                    if 0 <= val2_le <= 10000:
                                        humidity2_le = val2_le / 100.0
                                        if 0 <= humidity2_le <= 100:
                                            print(f"    ⭐ 可能是濕度2 (LE): {humidity2_le:.2f}%")
                                    
                                    if 0 <= val2_be <= 10000:
                                        humidity2_be = val2_be / 100.0
                                        if 0 <= humidity2_be <= 100:
                                            print(f"    ⭐ 可能是濕度2 (BE): {humidity2_be:.2f}%")
                                
                                # 如果是6 bytes，檢查第三個值
                                if len(value) >= 6:
                                    val3_le = struct.unpack('<H', value[4:6])[0]
                                    val3_be = struct.unpack('>H', value[4:6])[0]
                                    
                                    if 0 <= val3_le <= 10000:
                                        humidity3_le = val3_le / 100.0
                                        if 0 <= humidity3_le <= 100:
                                            print(f"    ⭐ 可能是濕度3 (LE): {humidity3_le:.2f}%")
                                    
                                    if 0 <= val3_be <= 10000:
                                        humidity3_be = val3_be / 100.0
                                        if 0 <= humidity3_be <= 100:
                                            print(f"    ⭐ 可能是濕度3 (BE): {humidity3_be:.2f}%")
                            
                        except Exception as e:
                            print(f"  讀取失敗: {e}")
                    
                    print()
            
            # 總結
            print("\n" + "=" * 70)
            print("所有讀取的數據總結")
            print("=" * 70)
            for uuid, info in all_readings.items():
                print(f"\n{uuid}")
                print(f"  服務: {info['service']}")
                print(f"  描述: {info['description']}")
                print(f"  數據: {info['hex']}")
                print(f"  長度: {len(info['data'])} bytes")
            
    except Exception as e:
        print(f"✗ 連接失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(analyze_all_characteristics())
    except KeyboardInterrupt:
        print("\n\n分析已取消")
