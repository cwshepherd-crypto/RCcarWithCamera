# Controller ESP32(Joystick FeatherWing ; MQTT Publisher)
# Joy FeatherWing + 0.96" 160x80 TFT + MQTT
# - Reads joystick + buttons from Joy FeatherWing (seesaw)
# - Publishes throttle/steer over MQTT for RC car
# - Shows joystick orientation & buttons on TFT

import time
import board
import displayio
import terminalio
import wifi
import socketpool
import ssl
import json
from micropython import const

import adafruit_minimqtt.adafruit_minimqtt as MQTT
from fourwire import FourWire
from adafruit_display_text import label
from adafruit_st7735r import ST7735R
from adafruit_seesaw.seesaw import Seesaw

# Configurations for MQTT Communication to work
# Boards must be enrolled int he school wifi
# 1883 : MQTT, unencrypted, unauthenticated on Free Mosquito Broker
WIFI_SSID = "Middlebury-IoT"
WIFI_PASS = "smuggle61hypnoses"
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_TOPIC = "rc/drive"

# Each button maps to the digital pin that will be used later by the seesaw library
# The Button_MASK simplifies having to check each button by making it one command
BUTTON_RIGHT = const(6)  
BUTTON_DOWN  = const(7)  
BUTTON_LEFT  = const(9)   
BUTTON_UP    = const(10)  
BUTTON_SEL   = const(14)  
BUTTON_MASK = (
    (1 << BUTTON_RIGHT)
    | (1 << BUTTON_DOWN)
    | (1 << BUTTON_LEFT)
    | (1 << BUTTON_UP)
    | (1 << BUTTON_SEL)
)

# Creates I2C bus that is used to communicate with the seesaw
# The seesaw allows us to communicate between the Joy Featherwing and ESP32 much easier by abstracting away data retrieval and transfer.
# Configure each of the buttons as inputs with pull-up resistors.
i2c = board.I2C()
ss = Seesaw(i2c, addr=0x49)
ss.pin_mode_bulk(BUTTON_MASK, ss.INPUT_PULLUP)

#Free previous display and set up SPI for same communication between Board and Display
displayio.release_displays()
spi = board.SPI()

# Wiring: GPIO13 -> CS
# GPIO12 -> DC
# GPIO27 -> RST
tft_cs = board.D13
tft_dc = board.D12
tft_reset = board.D27

#FourWire is a bus object for CircuitPython. It makes SPI communication much easier.
display_bus = FourWire(
    spi,
    command=tft_dc,
    chip_select=tft_cs,
    reset=tft_reset,
)

#Set up the TFT's display features.
display = ST7735R( 
    display_bus,
    width=160,
    height=80,
    rowstart=1,
    colstart=26,
    rotation=90,
    invert=True,
)

root = displayio.Group()
display.root_group = root

# Configures the background
bg_bitmap = displayio.Bitmap(160, 80, 1)
bg_palette = displayio.Palette(1)
bg_palette[0] = 0x000020 
bg_sprite = displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette)
root.append(bg_sprite)

# Title
title_label = label.Label(
    terminalio.FONT, text="RC Controller", color=0x00FFFF
)
title_label.anchor_point = (0.0, 0.0)
title_label.anchored_position = (2, 2)
root.append(title_label)

# Joystick raw values
joy_label = label.Label(
    terminalio.FONT, text="X: ----  Y: ----", color=0xFFFF00
)
joy_label.anchor_point = (0.0, 0.0)
joy_label.anchored_position = (2, 18)
root.append(joy_label)

# Joystick direction
dir_label = label.Label(
    terminalio.FONT, text="Dir: center", color=0xFFFFFF
)
dir_label.anchor_point = (0.0, 0.0)
dir_label.anchored_position = (2, 30)
root.append(dir_label)

# Throttle / Steer
axis_label = label.Label(
    terminalio.FONT, text="T:+0.00 S:+0.00", color=0x80FF80
)
axis_label.anchor_point = (0.0, 0.0)
axis_label.anchored_position = (2, 42)
root.append(axis_label)

# Buttons pressed
btn_label = label.Label(
    terminalio.FONT, text="Btns: none", color=0xFF80FF
)
btn_label.anchor_point = (0.0, 0.0)
btn_label.anchored_position = (2, 54)
root.append(btn_label)

# MQTT status
msg_label = label.Label(
    terminalio.FONT, text="WiFi: ...", color=0xFFA000
)
msg_label.anchor_point = (0.0, 0.0)
msg_label.anchored_position = (2, 66)
root.append(msg_label)

# Helper Function to make the joystick's direction readable on the TFT screen
def joystick_direction(x, y, low=350, high=650):
    if x < low:
        horiz = "left"
    elif x > high:
        horiz = "right"
    else:
        horiz = "center"

    if y < low:
        vert = "up"
    elif y > high:
        vert = "down"
    else:
        vert = "center"

    if horiz == "center" and vert == "center":
        return "center"
    if horiz == "center":
        return vert
    if vert == "center":
        return horiz
    return f"{horiz}-{vert}"

#Helper Function to make the joystick's button's readable on the TFT screen
def buttons_pressed(mask_val):
    names = []
    if not (mask_val & (1 << BUTTON_RIGHT)):
        names.append("A")
    if not (mask_val & (1 << BUTTON_DOWN)):
        names.append("B")
    if not (mask_val & (1 << BUTTON_LEFT)):
        names.append("Y")
    if not (mask_val & (1 << BUTTON_UP)):
        names.append("X")
    if not (mask_val & (1 << BUTTON_SEL)):
        names.append("SEL")
    return names


# Maps the joystick's analog input into a directional output (1 = forward, 0 = still, -1 = backwards)
def map_axis(val, low=350, high=650):
    if val < low:
        return -1.0
    if val > high:
        return +1.0
    return 0.0

# Wifi and MQTT Setup
print("Connecting to WiFi...")
msg_label.text = "WiFi: connecting..."
try:
    # Try and connect to the WIFI using the predefined SSID and Password.
    wifi.radio.connect(WIFI_SSID, WIFI_PASS)
    print("Connected:", wifi.radio.ipv4_address)
    msg_label.text = "WiFi: OK"
except Exception as e:
    #Print error if wifi fails
    print("WiFi error:", e)
    msg_label.text = "WiFi: ERR"

# Socketpoool is used to manage network connections by sending and recieving data.
# Handles the underlying Wi-Fi connection easily and abstracts low level information
pool = socketpool.SocketPool(wifi.radio)
#Create standard SSL Context for secure connections
ssl_context = ssl.create_default_context()

# Creates an mqtt client object that is able to talk to broker
mqtt_client = MQTT.MQTT(
    broker=MQTT_BROKER,
    port=MQTT_PORT,
    socket_pool=pool,
    ssl_context=ssl_context,
)

try:
#   Try and connect to broker using client object
    mqtt_client.connect()
    print("MQTT connected!")
    msg_label.text = "MQTT: connected"
except Exception as e:
    print("MQTT connect failed:", e)
    msg_label.text = "MQTT: ERR"


#Now, the main loop that runs continuously to publish input.
    
UPDATE_MS = 40 #Interval between updates and information publishes to the broker
last_ms = 0

while True:
    now_ms = time.monotonic_ns() // 1_000_000
   # If the time passed from last publish is > 40 MS then enable another publish
    if now_ms - last_ms >= UPDATE_MS:
        last_ms = now_ms 

        # Read the X and Y coordinates from joystick using seesaw library.
        x = ss.analog_read(2)
        y = ss.analog_read(3)

        # Update the TFT with the joystick's raw values
        joy_label.text = f"X:{x:4d}  Y:{y:4d}"

        # Use helper function to get direction and update display
        direction = joystick_direction(y, x)
        dir_label.text = "Dir: " + direction

        # Use helper function to determine throttle and speed.
        #Throtte (up/down) & Steer (Left/Right)
        steer = map_axis(x)
        throttle = -map_axis(y)  # Up = forward
        axis_label.text = f"T:{throttle:+.2f} S:{steer:+.2f}"

        #Buttons (Which have been pressed)
        bmask = ss.digital_read_bulk(BUTTON_MASK)
        names = buttons_pressed(bmask)
        btn_label.text = "Btns: " + (",".join(names) if names else "none")

        # Publish over MQTT for the RC Car to subscribe and retrieve
        # Dictionary of string(key) and int(value)
        payload = json.dumps({
            "throttle": throttle,
            "steer": steer
        })

        try:
            #Try and publish the data to the broker.
            mqtt_client.publish(MQTT_TOPIC, payload)
            #Message's main use is debugging since (0,0) will still be sent to broker
            msg_label.text = "MQTT: sent"
        except Exception as e:
            msg_label.text = "MQTT: ERR"
            print("MQTT publish failed:", e)

        try:
            # Does a few things, but we are using it to tell broker to keep the connection alive.
            # The Joystick isn't subscribing to the broker, so it doesn't need any information from it.
            mqtt_client.loop()
        except Exception as e:
            print("MQTT loop error:", e)

    # Sleep for 5 milliseconds to not crush the CPU
    time.sleep(0.005)
