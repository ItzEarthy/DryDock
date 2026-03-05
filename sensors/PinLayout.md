# Pin layout for ESP32

### RFID-RC522
* 3.3V
* RST   ->  GPIO1
* GND
* IRQ   ->  Not Connected (optional)
* MISO  ->  GPIO13
* MOSI  ->  GPIO11
* SCK   ->  GPIO12
* SDA   ->  GPIO10

### AM2320 #1
* VDD
* SDA   ->  GPIO4
  * 10k Resistor to VCC
* GND
* SCL   ->  GPIO5
  * 10k Resistor to VCC

### AM2320 #2
* VDD
* SDA   ->  GPIO8
  * 10k Resistor to VCC
* GND
* SCL   ->  GPIO9
  * 10k Resistor to VCC

### ADAFRUIT NAU7802 24-bit ADC
* VIN
* AV    ->  Not Connected
* GND
* SCL   ->  GPIO 5
* SDA   ->  GPIO 4
* DRDY  ->  Not Connected
