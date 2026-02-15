#!/usr/bin/env python3
"""解析 MyCO2 設備的藍牙廣告數據和特徵值數據"""

import struct
from datetime import datetime

def parse_manufacturer_data(data_bytes):
    """解析製造商數據（Manufacturer Data）
    
    MyCO2 的製造商 ID 是 0x06d5
    根據之前看到的數據：00 08 7f 7e 0a 6a 78 72 2e 03
    """
    if len(data_bytes) < 2:
        return None
    
    # 製造商 ID (2 bytes, little-endian)
    manufacturer_id = struct.unpack('<H', data_bytes[0:2])[0]
    
    if manufacturer_id != 0x06d5:
        return None
    
    result = {
        'manufacturer_id': f'0x{manufacturer_id:04x}',
        'raw_data': data_bytes.hex()
    }
    
    # 解析剩餘數據
    if len(data_bytes) >= 4:
        # 可能的 CO2 值（2 bytes, big-endian）
        co2_value = struct.unpack('>H', data_bytes[2:4])[0]
        result['co2_ppm'] = co2_value
    
    if len(data_bytes) >= 6:
        # 可能的溫度值
        temp_raw = struct.unpack('>H', data_bytes[4:6])[0]
        result['temperature'] = temp_raw / 100.0
    
    if len(data_bytes) >= 8:
        # 可能的濕度值
        hum_raw = struct.unpack('>H', data_bytes[6:8])[0]
        result['humidity'] = hum_raw / 100.0
    
    return result


def parse_characteristic_data(uuid, data_bytes):
    """根據特徵值 UUID 解析數據"""
    result = {
        'uuid': uuid,
        'raw_hex': data_bytes.hex(),
        'length': len(data_bytes)
    }
    
    # 常見的環境感測器 UUID
    if len(data_bytes) >= 2:
        # 嘗試解析為 CO2 值
        co2_value = struct.unpack('>H', data_bytes[0:2])[0]
        result['co2_ppm'] = co2_value
        
        # 驗證是否為合理的 CO2 值（通常 400-5000 ppm）
        if 300 <= co2_value <= 10000:
            result['likely_co2'] = True
    
    if len(data_bytes) >= 4:
        # 可能是 CO2 + 溫度
        co2 = struct.unpack('>H', data_bytes[0:2])[0]
        temp_raw = struct.unpack('>H', data_bytes[2:4])[0]
        result['co2_ppm'] = co2
        result['temperature_raw'] = temp_raw
        result['temperature_c'] = temp_raw / 100.0
    
    if len(data_bytes) >= 6:
        # 可能是 CO2 + 溫度 + 濕度
        co2 = struct.unpack('>H', data_bytes[0:2])[0]
        temp_raw = struct.unpack('>H', data_bytes[2:4])[0]
        hum_raw = struct.unpack('>H', data_bytes[4:6])[0]
        result['co2_ppm'] = co2
        result['temperature_c'] = temp_raw / 100.0
        result['humidity_percent'] = hum_raw / 100.0
    
    # 嘗試 little-endian
    if len(data_bytes) >= 2:
        co2_le = struct.unpack('<H', data_bytes[0:2])[0]
        if 300 <= co2_le <= 10000:
            result['co2_ppm_le'] = co2_le
    
    return result


def parse_advertisement_data(metadata):
    """解析廣告數據"""
    result = {}
    
    if 'manufacturer_data' in metadata:
        for manufacturer_id, data in metadata['manufacturer_data'].items():
            if manufacturer_id == 0x06d5:  # MyCO2 的製造商 ID
                parsed = parse_manufacturer_data(data)
                if parsed:
                    result['manufacturer_data'] = parsed
    
    if 'service_data' in metadata:
        result['service_data'] = metadata['service_data']
    
    return result


def parse_myco2_manufacturer_data(data_bytes):
    """解析 MyCO2 的製造商數據
    
    格式：00 08 7f 7e 0a 6a 78 72 2e 03
    製造商 ID: 0x06d5 (1749)
    
    嘗試多種可能的數據格式
    """
    if len(data_bytes) < 2:
        return None
    
    result = {
        'raw_hex': data_bytes.hex(),
        'raw_bytes': list(data_bytes),
        'length': len(data_bytes)
    }
    
    # 方法1: 跳過前2個字節，然後解析
    if len(data_bytes) >= 4:
        # 嘗試 big-endian
        co2_be = struct.unpack('>H', data_bytes[2:4])[0]
        result['co2_be_2_4'] = co2_be
        
        # 嘗試 little-endian
        co2_le = struct.unpack('<H', data_bytes[2:4])[0]
        result['co2_le_2_4'] = co2_le
        
        # 檢查哪個值合理
        if 300 <= co2_be <= 10000:
            result['co2_ppm'] = co2_be
            result['co2_format'] = 'big-endian (bytes 2-4)'
        elif 300 <= co2_le <= 10000:
            result['co2_ppm'] = co2_le
            result['co2_format'] = 'little-endian (bytes 2-4)'
    
    # 方法2: 從不同位置開始解析
    if len(data_bytes) >= 6:
        # 嘗試 bytes 4-6
        val_4_6_be = struct.unpack('>H', data_bytes[4:6])[0]
        val_4_6_le = struct.unpack('<H', data_bytes[4:6])[0]
        result['value_4_6_be'] = val_4_6_be
        result['value_4_6_le'] = val_4_6_le
        
        # 如果這個值看起來像溫度（通常 0-50°C，以0.01為單位就是 0-5000）
        if 0 <= val_4_6_be <= 5000:
            result['temperature_c'] = val_4_6_be / 100.0
            result['temp_format'] = 'big-endian (bytes 4-6)'
        elif 0 <= val_4_6_le <= 5000:
            result['temperature_c'] = val_4_6_le / 100.0
            result['temp_format'] = 'little-endian (bytes 4-6)'
    
    # 方法3: 嘗試不同的組合
    # 7f 7e = 32638 (BE) 或 32383 (LE) - 都不太像 CO2
    # 但 7e 7f 反過來可能是 32383，還是不對
    
    # 方法4: 可能是 signed 值
    if len(data_bytes) >= 4:
        co2_signed_be = struct.unpack('>h', data_bytes[2:4])[0]
        co2_signed_le = struct.unpack('<h', data_bytes[2:4])[0]
        result['co2_signed_be'] = co2_signed_be
        result['co2_signed_le'] = co2_signed_le
    
    # 方法5: 可能是單字節值組合
    if len(data_bytes) >= 4:
        # 7f 7e 可能是兩個獨立的字節
        byte2 = data_bytes[2]
        byte3 = data_bytes[3]
        result['byte2'] = byte2
        result['byte3'] = byte3
        
        # 或者可能是 7f * 256 + 7e = 32638，但這看起來不對
        # 或者可能是其他編碼方式
    
    # 顯示所有可能的解析結果
    result['possible_values'] = []
    if 'co2_ppm' in result:
        result['possible_values'].append(f"CO2: {result['co2_ppm']} ppm")
    if 'temperature_c' in result:
        result['possible_values'].append(f"溫度: {result['temperature_c']:.2f}°C")
    
    return result


if __name__ == "__main__":
    # 測試解析
    print("MyCO2 數據解析工具")
    print("=" * 70)
    
    # 測試實際看到的製造商數據
    # 從掃描結果：b'\x00\x08\x7f~ jxsJ\x03'
    test_data = bytes([0x00, 0x08, 0x7f, 0x7e, 0x0a, 0x6a, 0x78, 0x72, 0x2e, 0x03])
    print(f"\n測試數據: {test_data.hex()}")
    print(f"長度: {len(test_data)} bytes")
    
    parsed = parse_myco2_manufacturer_data(test_data)
    if parsed:
        print("\n解析結果:")
        for key, value in parsed.items():
            print(f"  {key}: {value}")
        
        if 'co2_ppm' in parsed:
            print(f"\n✓ CO2 濃度: {parsed['co2_ppm']} ppm")
        if 'temperature_c' in parsed:
            print(f"✓ 溫度: {parsed['temperature_c']:.2f}°C")
        if 'humidity_percent' in parsed:
            print(f"✓ 濕度: {parsed['humidity_percent']:.2f}%")
    else:
        print("無法解析為 MyCO2 數據")
