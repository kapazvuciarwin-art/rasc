#!/usr/bin/env python3
"""檢查資料庫中的數據"""

import sqlite3
from datetime import datetime

DATABASE = "myco2_data.db"

conn = sqlite3.connect(DATABASE)
conn.row_factory = sqlite3.Row

# 檢查最近的數據
print("=" * 70)
print("最近的數據記錄（最後 10 筆）")
print("=" * 70)

rows = conn.execute("""
    SELECT timestamp, co2_ppm, temperature_c, humidity, rssi, raw_data
    FROM readings
    ORDER BY timestamp DESC
    LIMIT 10
""").fetchall()

for row in rows:
    print(f"\n時間: {row['timestamp']}")
    print(f"  CO2: {row['co2_ppm']} ppm" if row['co2_ppm'] else "  CO2: None")
    print(f"  溫度: {row['temperature_c']}°C" if row['temperature_c'] else "  溫度: None")
    print(f"  濕度: {row['humidity']}%" if row['humidity'] else "  濕度: None")
    print(f"  RSSI: {row['rssi']} dBm" if row['rssi'] else "  RSSI: None")
    if row['raw_data']:
        print(f"  原始數據: {row['raw_data']}")

# 統計
print("\n" + "=" * 70)
print("數據統計")
print("=" * 70)

stats = conn.execute("""
    SELECT 
        COUNT(*) as total,
        COUNT(co2_ppm) as co2_count,
        COUNT(temperature_c) as temp_count,
        COUNT(humidity) as humidity_count,
        MIN(timestamp) as first,
        MAX(timestamp) as last
    FROM readings
""").fetchone()

print(f"總記錄數: {stats['total']}")
print(f"有 CO2 數據: {stats['co2_count']}")
print(f"有溫度數據: {stats['temp_count']}")
print(f"有濕度數據: {stats['humidity_count']}")
print(f"最早記錄: {stats['first']}")
print(f"最新記錄: {stats['last']}")

conn.close()
