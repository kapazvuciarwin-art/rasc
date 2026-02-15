# rasc - Raspberry Pi Bluetooth Scanner

樹莓派藍牙掃描專案，主要用於掃描和解析 MyCO2 CO2 感測器設備的藍牙訊號。

## 功能

- ✅ **Web 監控儀表板** - 透過瀏覽器查看即時數據和歷史圖表
- ✅ **Telegram 通知** - 當感測器數值超過閾值時自動發送通知
- ✅ 掃描周遭的藍牙設備
- ✅ 重點監控 MyCO2 CO2 感測器設備
- ✅ 解析 MyCO2 的 BLE 廣告數據（使用 sensirion-ble 庫）
- ✅ 連接設備並讀取 BLE 特徵值
- ✅ 記錄感測器數據到 SQLite 資料庫
- ✅ WebSocket 即時數據推送
- ✅ 歷史數據圖表（可切換 1/6/24/48 小時）

## 安裝

```bash
cd rasc
source venv/bin/activate
pip install -r requirements.txt
```

## 使用

### 🌐 Web 監控網站（推薦）

```bash
python app.py
```

然後在瀏覽器開啟：`http://<樹莓派IP>:5005`

功能：
- 即時顯示 CO₂、溫度、濕度、RSSI
- WebSocket 即時更新
- 歷史數據折線圖（可切換 1/6/24/48 小時）
- 自動後台監控 MyCO2 設備
- Telegram 通知設定（點擊右上角「⚙️ 通知設定」）

### 📱 Telegram 通知設定

詳細設定說明請參考 [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md)

快速設定：
1. 在網站點擊「⚙️ 通知設定」
2. 創建 Telegram Bot（透過 @BotFather）
3. 獲取 Chat ID（透過 @userinfobot）
4. 填入 Bot Token 和 Chat ID
5. 設定各感測器的閾值
6. 點擊「測試通知」確認設定
7. 點擊「儲存設定」

### 開機自動啟動

```bash
# 啟用服務
systemctl --user daemon-reload
systemctl --user enable rasc.service
systemctl --user start rasc.service

# 查看狀態
systemctl --user status rasc.service
```

### 其他工具腳本

#### 1. 掃描 MyCO2 設備

```bash
python scan_myco2.py
```

#### 2. 連接設備並讀取完整數據

```bash
python read_myco2.py
```

#### 3. 簡化監控（命令列）

```bash
python simple_monitor.py
```

#### 4. 解析數據格式

```bash
python parse_myco2.py
```

## MyCO2 設備資訊

- **MAC 地址**: `C4:5D:83:A6:7F:7E`
- **設備名稱**: `MyCO2`
- **製造商 ID**: `0x06d5` (1749)
- **廣告數據格式**: `00 08 [數據]`

## 數據解析

### 解析方式

目前使用 **sensirion-ble 庫**解析廣告數據（Manufacturer Data），這是官方推薦的解析方式。

### 廣告數據（Manufacturer Data）
- ✅ **CO₂**: 透過 sensirion-ble 庫解析
- ✅ **溫度**: 透過 sensirion-ble 庫解析
- ✅ **濕度**: 透過 sensirion-ble 庫解析

### BLE 特徵值（已停用，保留代碼）
- ⚠️ **CO2**: 特徵值 `00007001` - 2 bytes, little-endian，範圍 300-10000 ppm
- ⚠️ **溫度**: 特徵值 `00007003` - 4 bytes，可能包含溫度和 CO2
- ⚠️ **通知**: 特徵值 `00008004` - 20 bytes，包含多個感測器讀數

> 注意：目前僅使用 sensirion-ble 庫解析廣告數據，其他解析方式已停用但代碼保留。

### 關鍵特徵值 UUID
- `00007001-b38d-4985-720e-0f993a68ee41`: CO2 讀數（2 bytes, little-endian）
- `00007003-b38d-4985-720e-0f993a68ee41`: 可能包含溫度和 CO2（4 bytes）
- `00008004-b38d-4985-720e-0f993a68ee41`: 通知數據（20 bytes）

## 資料庫結構

所有腳本都會使用 SQLite 資料庫 `myco2_data.db`，包含：

```sql
CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    co2_ppm INTEGER,
    temperature_c REAL,
    humidity REAL,
    raw_data TEXT,
    rssi INTEGER
)
```

資料庫會自動創建，所有感測器讀數都會自動記錄。

## 注意事項

- 需要藍牙權限（通常需要 sudo 或將用戶加入 bluetooth 群組）
- MyCO2 設備需要在範圍內並已開啟
- 某些功能可能需要設備已配對（目前測試時未配對也能讀取廣告數據）
