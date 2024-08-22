import asyncio

from bleak import BleakClient, BleakError, BleakScanner

# ESP32のデバイスを識別するためのUUID (これはデバイスにより異なります)
ESP32_UUIDs = ["08:B6:1F:B9:4F:FA"]

# ESP側のサービスのUUID
RX_UUID = "69ddb59c-d601-4ea4-ba83-44f679a670ba"  # RX Characteristic UUID (from ESP32 to Computer)


# コールバック関数: データが送信されたときに呼び出されます
# 0: なんもいないよ〜
# 1: きたよ〜ん
def notification_handler(sender: int, data: bytearray, **_kwargs):
    print(f"Received: {data.decode()} (from {sender})")


async def connect_to_device(device):
    client = BleakClient(device)
    try:
        await client.connect()
        print(f"Connected to {device.name} ({device.address})")

        # Characteristicの情報を得るために記述。本番ではコメントアウトしても良い
        for service in client.services:
            print("---------------------")
            print(f"service uuid:{service.uuid}, description:{service.description}")
            [print(f"{c.properties},{c.uuid}") for c in service.characteristics]

        await client.start_notify(RX_UUID, notification_handler)

        while True:
            await asyncio.sleep(1.0)

    except BleakError as e:
        print(f"Connection to {device.address} failed: {e}")

    finally:
        if client.is_connected:
            # RX_UUIDが存在する場合のみstop_notifyを呼び出す
            characteristics = [
                c for service in client.services for c in service.characteristics
            ]
            if any(c.uuid == RX_UUID for c in characteristics):
                await client.stop_notify(RX_UUID)
            await client.disconnect()
            print(f"Disconnected from {device.address}")


async def run():
    while True:
        print("Scanning for devices...")
        scanner = BleakScanner()
        devices = await scanner.discover()

        clients = []
        for device in devices:
            if device.address in ESP32_UUIDs:
                clients.append(device)

        for device in clients:
            await connect_to_device(device)

        # 再接続のために少し待機してから再度スキャンを開始
        await asyncio.sleep(5.0)


asyncio.run(run())
