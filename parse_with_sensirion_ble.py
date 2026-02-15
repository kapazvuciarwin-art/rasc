#!/usr/bin/env python3
"""使用 sensirion-ble 庫解析 MyCO2 數據"""

import asyncio
from bleak import BleakScanner
from sensirion_ble import SensirionBluetoothDeviceData
from bluetooth_sensor_state_data import BluetoothServiceInfo

MYCO2_MAC = "C4:5D:83:A6:7F:7E"
MYCO2_NAME = "MyCO2"

async def parse_with_sensirion_ble():
    """使用 sensirion-ble 解析 MyCO2"""
    print("=" * 70)
    print("使用 sensirion-ble 解析 MyCO2")
    print("=" * 70)
    
    # 掃描設備
    print("\n掃描 MyCO2 設備...")
    devices = await BleakScanner.discover(timeout=10)
    
    myco2_device = None
    for device in devices:
        if MYCO2_NAME.lower() in (device.name or "").lower() or device.address.upper() == MYCO2_MAC.upper():
            myco2_device = device
            print(f"✓ 找到 MyCO2: {device.address}")
            break
    
    if not myco2_device:
        print("✗ 未找到 MyCO2")
        return
    
    # 獲取設備詳情
    if hasattr(myco2_device, 'details') and 'props' in myco2_device.details:
        props = myco2_device.details['props']
        
        # 準備數據
        name = props.get('Name', MYCO2_NAME)
        address = myco2_device.address
        rssi = props.get('RSSI', -100)
        manufacturer_data = props.get('ManufacturerData', {})
        service_data = props.get('ServiceData', {})
        service_uuids = props.get('UUIDs', [])
        
        print(f"\n設備資訊:")
        print(f"  名稱: {name}")
        print(f"  地址: {address}")
        print(f"  RSSI: {rssi} dBm")
        print(f"  製造商數據: {manufacturer_data}")
        print(f"  服務數據: {service_data}")
        print(f"  服務 UUIDs: {service_uuids}")
        
        # 創建 BluetoothServiceInfo
        try:
            service_info = BluetoothServiceInfo(
                name=name,
                address=address,
                rssi=rssi,
                manufacturer_data=manufacturer_data,
                service_data=service_data,
                service_uuids=service_uuids,
                source="bleak"
            )
            
            print(f"\n✓ 成功創建 BluetoothServiceInfo")
            
            # 使用 sensirion-ble 解析
            parser = SensirionBluetoothDeviceData()
            
            print(f"\n檢查設備支持...")
            if parser.supported(service_info):
                print(f"✓ sensirion-ble 支持此設備")
                
                print(f"\n解析數據...")
                update = parser.update(service_info)
                
                print(f"\n解析結果:")
                print(f"  類型: {type(update)}")
                
                # 獲取感測器數據
                if hasattr(update, 'sensors'):
                    print(f"\n感測器數據:")
                    for sensor_key, sensor_value in update.sensors.items():
                        print(f"    {sensor_key}: {sensor_value}")
                
                # 獲取二進制數據
                if hasattr(update, 'binary_sensor_data'):
                    print(f"\n二進制感測器數據:")
                    for key, value in update.binary_sensor_data.items():
                        print(f"    {key}: {value}")
                
                # 獲取事件
                if hasattr(update, 'events'):
                    print(f"\n事件:")
                    for event in update.events:
                        print(f"    {event}")
                
            else:
                print(f"✗ sensirion-ble 不支持此設備")
                print(f"  可能需要特定的製造商 ID 或服務 UUID")
                
        except Exception as e:
            print(f"\n✗ 解析失敗: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(parse_with_sensirion_ble())
    except KeyboardInterrupt:
        print("\n測試已取消")
