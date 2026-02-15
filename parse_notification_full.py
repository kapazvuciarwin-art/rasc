#!/usr/bin/env python3
"""完整解析 MyCO2 通知數據（20 bytes），找出所有感測器數據"""

import struct

# 從之前的測試中看到的通知數據格式
# 範例: 0200a363305fef0100009d637d5ff10100000000 (20 bytes)

def parse_20byte_notification(data):
    """解析 20 bytes 的通知數據"""
    if len(data) != 20:
        return None
    
    result = {
        'raw_hex': data.hex(),
        'sequence': data[0],
        'parsed': {}
    }
    
    # 分析數據結構
    # 字節 0: 序號
    # 字節 1: 未知
    # 字節 2-4: 可能是第一個感測器值
    # 字節 4-6: 可能是第二個感測器值
    # 字節 6-8: 可能是第三個感測器值
    # ... 依此類推
    
    # 嘗試解析所有可能的 2-byte 值
    values = []
    for i in range(0, len(data)-1, 2):
        if i+2 <= len(data):
            val_le = struct.unpack('<H', data[i:i+2])[0]
            val_be = struct.unpack('>H', data[i:i+2])[0]
            values.append({
                'offset': i,
                'little_endian': val_le,
                'big_endian': val_be
            })
    
    result['all_values'] = values
    
    # 檢查 CO2 (通常 300-10000 ppm)
    for v in values:
        if 300 <= v['little_endian'] <= 10000:
            result['parsed']['co2_le'] = {
                'offset': v['offset'],
                'value': v['little_endian'],
                'unit': 'ppm'
            }
        if 300 <= v['big_endian'] <= 10000:
            result['parsed']['co2_be'] = {
                'offset': v['offset'],
                'value': v['big_endian'],
                'unit': 'ppm'
            }
    
    # 檢查溫度 (通常 0-50°C，除以100後)
    for v in values:
        temp_le = v['little_endian'] / 100.0
        temp_be = v['big_endian'] / 100.0
        if 0 <= temp_le <= 50:
            result['parsed'][f'temp_le_offset_{v["offset"]}'] = {
                'offset': v['offset'],
                'value': temp_le,
                'unit': '°C'
            }
        if 0 <= temp_be <= 50:
            result['parsed'][f'temp_be_offset_{v["offset"]}'] = {
                'offset': v['offset'],
                'value': temp_be,
                'unit': '°C'
            }
    
    # 檢查濕度 (通常 0-100%，除以100後)
    for v in values:
        hum_le = v['little_endian'] / 100.0
        hum_be = v['big_endian'] / 100.0
        if 0 <= hum_le <= 100:
            result['parsed'][f'humidity_le_offset_{v["offset"]}'] = {
                'offset': v['offset'],
                'value': hum_le,
                'unit': '%'
            }
        if 0 <= hum_be <= 100:
            result['parsed'][f'humidity_be_offset_{v["offset"]}'] = {
                'offset': v['offset'],
                'value': hum_be,
                'unit': '%'
            }
    
    return result


# 測試實際的通知數據
test_data_samples = [
    "0200a363305fef0100009d637d5ff10100000000",
    "03009463e85ff301000094632160f50100000000",
    "04008e638260f90100008e63ae60f90100000000",
]

print("=" * 70)
print("MyCO2 通知數據完整解析（尋找濕度）")
print("=" * 70)

for i, hex_data in enumerate(test_data_samples, 1):
    print(f"\n範例 {i}:")
    print(f"原始數據: {hex_data}")
    data = bytes.fromhex(hex_data)
    
    parsed = parse_20byte_notification(data)
    if parsed:
        print(f"序號: {parsed['sequence']}")
        print(f"\n所有 2-byte 值:")
        for v in parsed['all_values']:
            print(f"  偏移 {v['offset']:2d}: LE={v['little_endian']:6d} ({v['little_endian']/100.0:6.2f}) | BE={v['big_endian']:6d} ({v['big_endian']/100.0:6.2f})")
        
        print(f"\n解析出的感測器數據:")
        for key, info in parsed['parsed'].items():
            print(f"  {key}: {info['value']:.2f} {info['unit']} (偏移 {info['offset']})")
