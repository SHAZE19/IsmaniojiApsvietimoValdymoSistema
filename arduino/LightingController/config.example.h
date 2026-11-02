#pragma once
// Copy to config.h (ignored by Git). Use your PC's LAN IPv4 address, not 127.0.0.1.
const byte SERVER_IP[] = {192, 168, 1, 100};
const uint16_t SERVER_PORT = 8001;
// Set a free static IP in your subnet, outside the router's DHCP pool.
const byte DEVICE_IP[] = {192, 168, 1, 210};
const byte GATEWAY_IP[] = {192, 168, 1, 1};
const byte SUBNET_MASK[] = {255, 255, 255, 0};
const byte DEVICE_MAC[] = {0x02, 0x53, 0x48, 0x56, 0x01, 0x01};
// Paste backend/data/device-secret.txt here. Never commit config.h.
const char DEVICE_KEY[] = "PASTE_THE_GENERATED_DEVICE_KEY_HERE";
const byte PN532_IRQ = 2;
const byte PN532_RESET = 7;
const byte PIR_PIN = 3;
const byte RELAY_PIN = 8;
const byte PWM_PIN = 5;
const bool RELAY_ACTIVE_LOW = true;
