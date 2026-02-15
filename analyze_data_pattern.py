#!/usr/bin/env python3
"""分析數據模式，找出正確的解析方式"""

import sqlite3
import struct
from collections import defaultdict

conn = sqlite3.connect('myco2_data.db')
conn.row_factory = sqlite3.Row

# 獲取所有有原始數據的記錄
rows = conn.execute("""
    SELECT timestamp, co2_ppm, temperature_c, humidity, raw_data
    FROM readings
    WHERE raw_data IS NOT NULL
    ORDER BY timestamp DESC
    LIMIT 50
""").fetchall()

print("=" * 70)
print("數據模式分析")
print("=" * 70)

# 按數據長度分組
by_length = defaultdict(list)
for row in rows:
    data_len = len(row['raw_data']) // 2
    by_length[data_len].append(row)

print(f"\n按數據長度分組:")
for length, records in sorted(by_length.items()):
    print(f"  {length} bytes: {len(records)} 筆記錄")

# 分析 20 bytes 的數據（通知數據）
if 20 in by_length:
    print("\n" + "=" * 70)
    print("分析 20 bytes 通知數據")
    print("=" * 70)
    
    samples = by_length[20][:5]  # 取前5個樣本
    for i, row in enumerate(samples, 1):
        data = bytes.fromhex(row['raw_data'])
        print(f"\n樣本 {i}:")
        print(f"  CO2: {row['co2_ppm']}")
        print(f"  溫度: {row['temperature_c']}")
        print(f"  濕度: {row['humidity']}")
        print(f"  原始: {row['raw_data']}")
        
        # 分析每個 2-byte 值
        print(f"  所有 2-byte 值 (little-endian):")
        for j in range(0, len(data)-1, 2):
            val_le = struct.unpack('<H', data[j:j+2])[0]
            val_be = struct.unpack('>H', data[j:j+2])[0]
            print(f"    bytes {j:2d}-{j+2:2d}: LE={val_le:6d} ({val_le/100.0:6.2f}) | BE={val_be:6d} ({val_be/100.0:6.2f})")

# 分析 4 bytes 的數據（可能是溫度特徵值）
if 4 in by_length:
    print("\n" + "=" * 70)
    print("分析 4 bytes 數據（溫度特徵值）")
    print("=" * 70)
    
    samples = by_length[4][:5]
    for i, row in enumerate(samples, 1):
        data = bytes.fromhex(row['raw_data'])
        print(f"\n樣本 {i}:")
        print(f"  溫度: {row['temperature_c']}")
        print(f"  原始: {row['raw_data']}")
        
        if len(data) >= 4:
            val1_le = struct.unpack('<H', data[0:2])[0]
            val1_be = struct.unpack('>H', data[0:2])[0]
            val2_le = struct.unpack('<H', data[2:4])[0]
            val2_be = struct.unpack('>H', data[2:4])[0]
            
            print(f"  bytes 0-2: LE={val1_le} ({val1_le/100.0:.2f}) | BE={val1_be} ({val1_be/100.0:.2f})")
            print(f"  bytes 2-4: LE={val2_le} ({val2_le/100.0:.2f}) | BE={val2_be} ({val2_be/100.0:.2f})")
            
            # 檢查哪個值最接近實際溫度
            if row['temperature_c']:
                actual_temp = row['temperature_c']
                print(f"  實際溫度: {actual_temp}°C")
                print(f"  差異: |{val1_le/100.0 - actual_temp:.2f}|, |{val1_be/100.0 - actual_temp:.2f}|, |{val2_le/100.0 - actual_temp:.2f}|, |{val2_be/100.0 - actual_temp:.2f}|")

# 分析 2 bytes 的數據（CO2）
if 2 in by_length:
    print("\n" + "=" * 70)
    print("分析 2 bytes 數據（CO2）")
    print("=" * 70)
    
    samples = by_length[2][:5]
    for i, row in enumerate(samples, 1):
        data = bytes.fromhex(row['raw_data'])
        print(f"\n樣本 {i}:")
        print(f"  CO2: {row['co2_ppm']}")
        print(f"  原始: {row['raw_data']}")
        
        if len(data) >= 2:
            val_le = struct.unpack('<H', data[0:2])[0]
            val_be = struct.unpack('>H', data[0:2])[0]
            print(f"  LE={val_le} | BE={val_be}")
            print(f"  → CO2 應該是: {row['co2_ppm']}")

conn.close()
