// Arduino UNO + PN532 (I2C) + W5100 (SPI) + PIR + relay + logic-level MOSFET.
// Libraries: Ethernet 2.x, Adafruit PN532 1.x, ArduinoJson 6.21.5.
#include <SPI.h>
#include <Wire.h>
#include <Ethernet.h>
#include <Adafruit_PN532.h>
#include <ArduinoJson.h>
#include "config.h"

Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET);
EthernetClient client;
enum Mode { AUTO, MANUAL_ON, MANUAL_OFF };
Mode mode = AUTO;
byte normalBrightness = 100, dimBrightness = 25, actualBrightness = 0;
unsigned long dimAfter = 60000UL, offAfter = 120000UL;
unsigned long lastActivity = 0, lastSync = 0, lastAttempt = 0, lastScan = 0;
bool autoActive = false, nfcReady = false, pendingMotion = false;
char previousUid[21] = "";
bool haveServer = false;

void output(byte brightness) {
  actualBrightness = brightness;
  // Relay only switches power. PWM MUST drive a MOSFET, never the relay.
  digitalWrite(RELAY_PIN, (brightness > 0) == RELAY_ACTIVE_LOW ? LOW : HIGH);
  analogWrite(PWM_PIN, map(brightness, 0, 100, 0, 255));
}

bool request(const __FlashStringHelper *path, const char *body) {
  client.stop();
  if (!client.connect(IPAddress(SERVER_IP), SERVER_PORT)) return false;
  client.print(body ? F("POST ") : F("GET "));
  client.print(path); client.println(F(" HTTP/1.0"));
  client.print(F("Host: ")); client.println(IPAddress(SERVER_IP));
  client.print(F("X-Device-Key: ")); client.println(DEVICE_KEY);
  client.println(F("Connection: close"));
  if (body) {
    client.println(F("Content-Type: application/json"));
    client.print(F("Content-Length: ")); client.println(strlen(body));
  }
  client.println();
  if (body) client.print(body);
  char status[24];
  size_t count = client.readBytesUntil('\n', status, sizeof(status) - 1);
  status[count] = 0;
  if (!strstr(status, " 200 ") || !client.find("\r\n\r\n")) { client.stop(); return false; }
  StaticJsonDocument<384> doc;
  DeserializationError error = deserializeJson(doc, client);
  client.stop();
  if (error || !doc.containsKey("desired_brightness")) return false;
  const char *modeText = doc["mode"] | "off";
  mode = strcmp(modeText, "auto") == 0 ? AUTO : strcmp(modeText, "on") == 0 ? MANUAL_ON : MANUAL_OFF;
  normalBrightness = constrain(doc["brightness"] | 100, 1, 100);
  dimBrightness = constrain(doc["dim_brightness"] | 25, 1, 50);
  dimAfter = (doc["dim_after_seconds"] | 60UL) * 1000UL;
  offAfter = (doc["off_after_seconds"] | 120UL) * 1000UL;
  byte desired = constrain(doc["desired_brightness"] | 0, 0, 100);
  autoActive = mode == AUTO && desired > 0;
  unsigned long remaining = doc["remaining_seconds"] | 0UL;
  if (autoActive) lastActivity = millis() - (offAfter - min(offAfter, remaining * 1000UL));
  lastSync = millis(); haveServer = true;
  output(desired);
  if (doc.containsKey("authorized")) {
    Serial.println(doc["authorized"].as<bool>() ? F("NFC: prieiga suteikta") : F("NFC: prieiga atmesta"));
  }
  return true;
}

void localAutomation() {
  unsigned long now = millis();
  if (mode == MANUAL_OFF) { output(0); return; }
  if (mode == MANUAL_ON) {
    // A lost connection cannot leave a remote command active indefinitely.
    output(haveServer && now - lastSync < offAfter ? normalBrightness : 0);
    return;
  }
  if (!autoActive) { output(0); return; }
  if (digitalRead(PIR_PIN) == HIGH) lastActivity = now;
  unsigned long elapsed = now - lastActivity;
  if (elapsed >= offAfter) { autoActive = false; output(0); }
  else output(elapsed >= dimAfter ? min(normalBrightness, dimBrightness) : normalBrightness);
}

void setup() {
  Serial.begin(115200);
  digitalWrite(RELAY_PIN, RELAY_ACTIVE_LOW ? HIGH : LOW);
  pinMode(RELAY_PIN, OUTPUT); pinMode(PWM_PIN, OUTPUT); pinMode(PIR_PIN, INPUT);
  output(0);
  // W5100 uses D10-D13; disable the Ethernet shield's SD card chip select (D4).
  pinMode(4, OUTPUT); digitalWrite(4, HIGH);
  byte mac[6]; memcpy(mac, DEVICE_MAC, sizeof(mac));
  Ethernet.init(10);
  Ethernet.begin(mac, IPAddress(DEVICE_IP), IPAddress(GATEWAY_IP), IPAddress(GATEWAY_IP), IPAddress(SUBNET_MASK));
  Ethernet.setRetransmissionTimeout(500); Ethernet.setRetransmissionCount(1);
  client.setConnectionTimeout(1000); client.setTimeout(1000);
  nfc.begin();
  nfcReady = nfc.getFirmwareVersion() != 0;
  if (nfcReady) {
    nfc.SAMConfig(); nfc.setPassiveActivationRetries(0x01);
    nfc.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
  } else Serial.println(F("PN532 nerastas. Patikrinkite I2C ir jungiklius."));
  request(F("/api/device/state"), NULL);
  Serial.println(F("Sistema paleista. PIR jutikliui leiskite stabilizuotis."));
}

void loop() {
  unsigned long now = millis();
  bool motion = digitalRead(PIR_PIN) == HIGH;
  pendingMotion = pendingMotion || motion;
  localAutomation();
  // IRQ-driven detection avoids blocking the timer while waiting for a card.
  if (nfcReady && digitalRead(PN532_IRQ) == LOW) {
    uint8_t uid[10], length;
    // This Adafruit readDetectedPassiveTargetID implementation reads 4/7-byte UIDs.
    if (nfc.readDetectedPassiveTargetID(uid, &length) && (length == 4 || length == 7)) {
      char hex[21];
      for (byte i = 0; i < length; ++i) sprintf(hex + 2 * i, "%02X", uid[i]);
      hex[2 * length] = 0;
      if (strcmp(hex, previousUid) != 0 || now - lastScan > 3000UL) {
        strcpy(previousUid, hex); lastScan = now;
        Serial.print(F("Korteles UID: ")); Serial.println(hex);
        char body[40]; snprintf(body, sizeof(body), "{\"card_id\":\"%s\"}", hex);
        if (!request(F("/api/nfc/authorize"), body)) Serial.println(F("Serveris nepasiekiamas: nauja prieiga nesuteikiama."));
      }
    }
    nfc.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
  }
  if (now - lastAttempt >= 2000UL) {
    lastAttempt = now;
    char body[64];
    snprintf(body, sizeof(body), "{\"motion\":%s,\"actual_brightness\":%u}", pendingMotion ? "true" : "false", actualBrightness);
    if (request(F("/api/device/telemetry"), body)) pendingMotion = false;
  }
}
