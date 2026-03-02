## RFID-RC522 Module

The [RFID-RC522 module](https://esp32io.com/tutorials/esp32-rfid-nfc) is a low-cost MFRC522-based RFID reader/writer. It operates in the High Frequency (13.56 MHz) range and supports various RFID tags and cards (NFC).

### Pinout

The RFID-RC522 module has 8 pins, some pins are shared among three communication interfaces: SPI, I2C, UART. At a time, only one communication mode can be used. The pins are:

* **GND pin:** connect this pin to GND (0V)
* **VCC pin:** connect this pin to VCC (3.3V)
* **RST pin:** is a pin for reset and power-down. When this pin goes low, hard power-down is enabled. On the rising edge, the module is reset.
* **IRQ pin:** is an interrupt pin that can alert the ESP32 when RFID tag comes into its detection range.
* **MISO/SCL/TX pin:** works as MISO pin (SPI), SCL pin (I2C), or TX pin (UART).
* **MOSI pin:** works as MOSI if SPI interface is enabled.
* **SCK pin:** works as SCK if SPI interface is enabled.
* **SS/SDA/RX pin:** works as SS pin (SPI), SDA pin (I2C), or RX pin (UART).

**NOTE:**
* The pins order can vary according to manufacturers. ALWAYS use the labels printed on the module.
* The RFID-RC522 module works with **3.3V**. Do not connect the VCC pin to 5V, as it can burn the module.
* Most tutorials use the **SPI interface** for communication between the ESP32 and the RFID-RC522 module.
