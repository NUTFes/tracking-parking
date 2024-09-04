#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

//---------------------------------------------------------
// Constants
//---------------------------------------------------------
#define SERVICE_UUID "55725ac1-066c-48b5-8700-2d9fb3603c5e"
#define CHARACTERISTIC_UUID "69ddb59c-d601-4ea4-ba83-44f679a670ba"
#define BLE_DEVICE_NAME "MyBLEDevice"
#define LED_PIN 22
#define BUTTON_PIN 23
#define echoPin 16 // Echo Pin
#define trigPin 17 // Trigger Pin

//---------------------------------------------------------
// Variables
//---------------------------------------------------------
BLEServer *pServer = NULL;
BLECharacteristic *pCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;
std::string rxValue;
std::string txValue;
bool bleOn = false;
bool buttonPressed = false;
int carFlag = 0;

double Duration = 0; //受信した間隔
double Distance = 0; //距離
double thresholdDistance = 50; //検出閾値[cm]

//---------------------------------------------------------
// Callbacks
//---------------------------------------------------------
class MyServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *pServer) {
    deviceConnected = true;
    Serial.println("onConnect");
  };
  void onDisconnect(BLEServer *pServer) {
    deviceConnected = false;
    Serial.println("onDisconnect");
  }
};

class MyCharacteristicCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *pCharacteristic) {
    Serial.println("onWrite");
    std::string rxValue = pCharacteristic->getValue();
    if (rxValue.length() > 0) {
      bleOn = rxValue[0] != 0;
      Serial.print("Received Value: ");
      for (int i = 0; i < rxValue.length(); i++) {
        Serial.print(rxValue[i], HEX);
      }
      Serial.println();
    }
  }
};

//---------------------------------------------------------
void setup() {
  //
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  pinMode( echoPin, INPUT );
  pinMode( trigPin, OUTPUT );

  Serial.begin(115200);
  //
  BLEDevice::init(BLE_DEVICE_NAME);
  // Server
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  // Service
  BLEService *pService = pServer->createService(SERVICE_UUID);
  // Characteristic
  pCharacteristic = pService->createCharacteristic(
    CHARACTERISTIC_UUID,
    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_NOTIFY);
  pCharacteristic->setCallbacks(new MyCharacteristicCallbacks());
  pCharacteristic->addDescriptor(new BLE2902());
  //
  pService->start();
  // Advertising
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(false);
  pAdvertising->setMinPreferred(0x0);
  BLEDevice::startAdvertising();
  Serial.println("startAdvertising");
}

//---------------------------------------------------------
void loop() {
  // disconnecting
  if (!deviceConnected && oldDeviceConnected) {
    delay(500);  // give the bluetooth stack the chance to get things ready
    pServer->startAdvertising();
    Serial.println("restartAdvertising");
    oldDeviceConnected = deviceConnected;
  }
  // connecting
  if (deviceConnected && !oldDeviceConnected) {
    oldDeviceConnected = deviceConnected;
  }
  // LED
  digitalWrite(LED_PIN, bleOn ? HIGH : LOW);

  //超音波センサ
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2); 
  digitalWrite( trigPin, HIGH ); //超音波を出力
  delayMicroseconds( 10 ); //
  digitalWrite( trigPin, LOW );
  Duration = pulseIn( echoPin, HIGH ); //センサからの入力
  
  if (Duration > 0) {
    Duration = Duration/2; //往復距離を半分にする
    Distance = Duration*340*100/1000000; // 音速を340m/sに設定
    //Distance[cm]
    if (Distance  >=  thresholdDistance) {
      carFlag = 0;
      String str = "CarFlag:" + String(carFlag);
      Serial.println(str);
      // Notify
      if (deviceConnected) {
        txValue = str.c_str();
        pCharacteristic->setValue(txValue);
        pCharacteristic->notify();
      }
      // buttonPressed = true;
      delay(50);
    }
    else {
      carFlag = 1;
        String str = "CarFlag:" + String(carFlag);
        Serial.println(str);
        // Notify
        if (deviceConnected) {
          txValue = str.c_str();
          pCharacteristic->setValue(txValue);
          pCharacteristic->notify();
        }
        // buttonPressed = true;
        delay(50);
    }
  }
  else{
    carFlag = 0;
    String str = "CarFlag:" + String(carFlag);
    Serial.println(str);
    // Notify
    if (!deviceConnected) {
      txValue = str.c_str();
      pCharacteristic->setValue(txValue);
      pCharacteristic->notify();
    }
    // buttonPressed = false;
    delay(50);
  }
  // Serial.println(Distance);
  // if (_hoge = 1) {
  
  // }
  
  // _hoge = 1;


  // Serial.println("hoge");
  // carFlag = 2;
  // String str = "CarFlag:" + String(carFlag);
  // Serial.println(str);
  // // Notify
  // if (deviceConnected) {
  //   txValue = str.c_str();
  //   pCharacteristic->setValue(txValue);
  //   pCharacteristic->notify();
  // }
  delay(1000);
}