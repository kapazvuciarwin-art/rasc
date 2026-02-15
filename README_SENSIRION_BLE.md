# sensirion-ble 解析方式說明

## 概述

已整合 `sensirion-ble` 庫作為新的解析方式，同時保留原有的原始解析代碼作為備份。

## 兩種解析方式

### 1. sensirion-ble 庫（新方式 - 優先使用）

**優點**：
- ✅ 官方庫，解析邏輯經過驗證
- ✅ 自動識別 Sensirion 設備
- ✅ 從廣告數據（Manufacturer Data）直接解析
- ✅ 解析結果：溫度、濕度、CO2 都正確

**使用時機**：
- 掃描設備時，從廣告數據解析
- 製造商 ID: `0x06d5` (1749)

**解析結果範例**：
```python
{
    'temperature_c': 27.5,
    'humidity': 44.7,
    'co2_ppm': 814
}
```

### 2. 原始解析方式（備份）

**使用時機**：
- 20 bytes 通知數據解析
- sensirion-ble 解析失敗時的備份

**數據格式**：
- CO2: bytes 14-16 (little-endian)
- 溫度: bytes 2-4 (little-endian, 除以1000)
- 濕度: bytes 4-6 (little-endian, 除以1000)

## 整合方式

在 `app.py` 中：

1. **掃描時**：優先使用 sensirion-ble 解析廣告數據
2. **通知時**：使用原始解析方式處理 20 bytes 通知數據
3. **備份機制**：如果 sensirion-ble 不可用，自動回退到原始解析

## 測試

```bash
# 測試 sensirion-ble 解析
cd /home/kapraspi/rasc
source venv/bin/activate
python3 parse_with_sensirion_ble.py
```

## 注意事項

- sensirion-ble 主要用於解析廣告數據（Manufacturer Data）
- 20 bytes 通知數據仍使用原始解析方式
- 兩種方式可以同時使用，互不衝突
