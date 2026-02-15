#!/usr/bin/env python3
"""分析 MyCO2 通知數據格式"""

import struct

# 從實際通知數據分析格式
# 範例: 0200a363305fef0100009d637d5ff10100000000 (20 bytes)

def parse_notification_data(data_bytes):
    """解析 MyCO2 通知數據（20 bytes）"""
    if len(data_bytes) != 20:
        return {'error': f'數據長度錯誤: {len(data_bytes)} bytes'}
    
    result = {
        'raw_hex': data_bytes.hex(),
        'length': len(data_bytes)
    }
    
    # 分析格式
    # 字節 0: 序號或類型
    result['sequence'] = data_bytes[0]
    
    # 嘗試多種解析方式
    # 方式1: 字節 1-2 可能是某個值
    if len(data_bytes) >= 3:
        val_1_2 = struct.unpack('<H', data_bytes[1:3])[0]
        result['val_1_2'] = val_1_2
    
    # 方式2: 字節 2-4 可能是 CO2 (little-endian)
    if len(data_bytes) >= 5:
        co2_le = struct.unpack('<H', data_bytes[2:4])[0]
        result['co2_2_4_le'] = co2_le
        if 300 <= co2_le <= 10000:
            result['co2_ppm'] = co2_le
    
    # 方式3: 字節 4-6 可能是溫度
    if len(data_bytes) >= 7:
        temp_le = struct.unpack('<H', data_bytes[4:6])[0]
        result['temp_4_6_le'] = temp_le
        # 溫度可能是以 0.01°C 為單位
        temp_c = temp_le / 100.0
        if 0 <= temp_c <= 50:
            result['temperature_c'] = temp_c
    
    # 方式4: 字節 6-8 可能是另一個 CO2 值
    if len(data_bytes) >= 9:
        co2_6_8_le = struct.unpack('<H', data_bytes[6:8])[0]
        result['co2_6_8_le'] = co2_6_8_le
        if 300 <= co2_6_8_le <= 10000:
            result['co2_ppm_alt'] = co2_6_8_le
    
    # 方式5: 字節 8-10 可能是另一個溫度值
    if len(data_bytes) >= 11:
        temp_8_10_le = struct.unpack('<H', data_bytes[8:10])[0]
        result['temp_8_10_le'] = temp_8_10_le
        temp_c_alt = temp_8_10_le / 100.0
        if 0 <= temp_c_alt <= 50:
            result['temperature_c_alt'] = temp_c_alt
    
    # 方式6: 查看是否有模式
    # 從實際數據看，可能是兩個感測器讀數的組合
    # 字節 2-8 可能是第一個讀數，字節 10-16 可能是第二個讀數
    
    # 嘗試解析為兩個獨立的讀數
    # 第一個讀數組 (字節 2-8)
    if len(data_bytes) >= 9:
        # CO2 (2 bytes, little-endian)
        co2_1 = struct.unpack('<H', data_bytes[2:4])[0]
        # 溫度 (2 bytes, little-endian, 除以100)
        temp_1_raw = struct.unpack('<H', data_bytes[4:6])[0]
        temp_1 = temp_1_raw / 100.0
        # 其他值
        other_1 = struct.unpack('<H', data_bytes[6:8])[0]
        
        result['reading_1'] = {
            'co2_ppm': co2_1 if 300 <= co2_1 <= 10000 else None,
            'temperature_c': temp_1 if 0 <= temp_1 <= 50 else None,
            'other': other_1
        }
    
    # 第二個讀數組 (字節 10-16)
    if len(data_bytes) >= 17:
        co2_2 = struct.unpack('<H', data_bytes[10:12])[0]
        temp_2_raw = struct.unpack('<H', data_bytes[12:14])[0]
        temp_2 = temp_2_raw / 100.0
        other_2 = struct.unpack('<H', data_bytes[14:16])[0]
        
        result['reading_2'] = {
            'co2_ppm': co2_2 if 300 <= co2_2 <= 10000 else None,
            'temperature_c': temp_2 if 0 <= temp_2 <= 50 else None,
            'other': other_2
        }
    
    return result


if __name__ == "__main__":
    # 測試實際的通知數據
    test_data = bytes.fromhex("0200a363305fef0100009d637d5ff10100000000")
    print("測試通知數據解析")
    print("=" * 70)
    print(f"原始數據: {test_data.hex()}")
    print()
    
    parsed = parse_notification_data(test_data)
    print("解析結果:")
    for key, value in parsed.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 70)
    print("可能的感測器讀數:")
    if 'reading_1' in parsed:
        r1 = parsed['reading_1']
        print(f"  讀數1:")
        if r1['co2_ppm']:
            print(f"    CO2: {r1['co2_ppm']} ppm")
        if r1['temperature_c']:
            print(f"    溫度: {r1['temperature_c']:.2f}°C")
    
    if 'reading_2' in parsed:
        r2 = parsed['reading_2']
        print(f"  讀數2:")
        if r2['co2_ppm']:
            print(f"    CO2: {r2['co2_ppm']} ppm")
        if r2['temperature_c']:
            print(f"    溫度: {r2['temperature_c']:.2f}°C")
