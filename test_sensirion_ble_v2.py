#!/usr/bin/env python3
"""使用 sensirion-ble 庫解析 MyCO2 數據（正確的方式）"""

import asyncio
from bleak import BleakScanner
from sensirion_ble import SensirionBluetoothDeviceData
from bluetooth_sensor_state_data import BluetoothServiceInfo
from bluetooth_adapters import BluetoothAdapters

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"

async def test_sensirion_ble_v2():
    """測試 sensirion-ble 庫 - 正確的方式"""
    print("=" * 70)
    print("測試 sensirion-ble 庫解析 MyCO2")
    print("=" * 70)
    
    # 掃描設備
    print("\n掃描 MyCO2 設備...")
    devices = await BleakScanner.discover(timeout=10)
    
    myco2_device = None
    for device in devices:
        if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
            myco2_device = device
            print(f"✓ 找到 MyCO2: {device.address}")
            
            # 顯示設備詳情
            if hasattr(device, 'details') and 'props' in device.details:
                props = device.details['props']
                print(f"  RSSI: {props.get('RSSI', 'N/A')} dBm")
                print(f"  名稱: {props.get('Name', 'N/A')}")
                
                # 獲取製造商數據
                if 'ManufacturerData' in props:
                    mfg_data = props['ManufacturerData']
                    print(f"  製造商數據: {mfg_data}")
                    
                    # 嘗試使用 sensirion-ble 解析
                    try:
                        # 創建 BluetoothServiceInfo
                        # 需要適配器、地址、名稱、RSSI、製造商數據等
                        service_info = BluetoothServiceInfo(
                            name=props.get('Name', ''),
                            address=device.address,
                            rssi=props.get('RSSI', -100),
                            manufacturer_data=mfg_data,
                            service_data={},
                            service_uuids=[],
                            source="test"
                        )
                        
                        # 創建 SensirionBluetoothDeviceData
                        parser = SensirionBluetoothDeviceData()
                        
                        # 檢查是否支持
                        if parser.supported(service_info):
                            print(f"\n✓ sensirion-ble 支持此設備")
                            
                            # 更新數據
                            update = parser.update(service_info)
                            print(f"\n解析結果:")
                            print(f"  {update}")
                            
                            # 獲取感測器數據
                            if hasattr(update, 'sensors'):
                                for sensor_key, sensor_value in update.sensors.items():
                                    print(f"  {sensor_key}: {sensor_value}")
                        else:
                            print(f"\n✗ sensirion-ble 不支持此設備")
                            
                    except Exception as e:
                        print(f"\n解析時出錯: {e}")
                        import traceback
                        traceback.print_exc()
            
            break
    
    if not myco2_device:
        print("✗ 未找到 MyCO2")


if __name__ == "__main__":
    try:
        asyncio.run(test_sensirion_ble_v2())
    except KeyboardInterrupt:
        print("\n測試已取消")
