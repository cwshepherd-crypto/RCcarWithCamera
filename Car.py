# Car: Motor Controller (MQTT Sub)
# DC Motor + Stepper FeatherWing
# Motor FeatherWing + MQTT
# - Receives JSON { "throttle": x, "steer": y } and converts to differential drive
# - Inverts throttle/steer to correct for upside-down motor mounting
# - Drives LEFT (motor3) and RIGHT (motor4) with clamped values [-1, 1]

import time
import board
import json
import wifi
import socketpool
import ssl
import adafruit_minimqtt.adafruit_minimqtt as MQTT
from adafruit_motorkit import MotorKit


# Configurations for MQTT Communication to work
# Boards must be enrolled int he school wifi
# 1883 : MQTT, unencrypted, unauthenticated on Free Mosquito Broker
WIFI_SSID = "Middlebury-IoT"
WIFI_PASS = "garlands73dissinew"

MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_TOPIC = "rc/drive"

# Set up the MotorKit using adafruit's motorkit library
kit = MotorKit(i2c=board.I2C())
LEFT = kit.motor3
RIGHT = kit.motor4

#Used to stop both motors simultaneously.
def stop_all():
    LEFT.throttle = 0
    RIGHT.throttle = 0

stop_all()

# Wifi and MQTT Setup
print("Connecting to WiFi...")
try:
   # Try and connect to the WIFI using the predefined SSID and Password.
    wifi.radio.connect(WIFI_SSID, WIFI_PASS)
    print("Connected:", wifi.radio.ipv4_address)
except Exception as e:
    # Print error if wifi fails
    print("WiFi error:", e)
    
# Socketpoool is used to manage network connections by sending and recieving data.
# Handles the underlying Wi-Fi connection with broker easily and abstracts low level information
pool = socketpool.SocketPool(wifi.radio)
ssl_context = ssl.create_default_context()

# Function called when an MQTT message arrives for the subscriber
def on_message(client, topic, message):
    global last_msg_time  # Needs to be global so it can be changed in loop
    last_msg_time = time.monotonic()  #Reset last message's time to be current time
    print("Message:", message)
    try:
        #Here, try and parse the json file sent over MQTT to get throttle and steer data
        #Changing its type (Dictionary ->(To Broker) -> String ->(To Subscriber) Dictionary
        data = json.loads(message)
        throttle = float(data["throttle"])
        steer = float(data["steer"])
        
        #We placed the motors on upside down, so we correct for this by inversing the sign of throttle and steer
        throttle = -throttle
        steer = -steer
    except:
        print("Invalid JSON")
        return

    #if both values will be 0, the robot will stop
    # if throttle is positive, the robot will go forward, if negative - backward
    # if throttle is 0, but there is some steering, robot will turn in place
    # Inspired by method from: https://robotics.stackexchange.com/questions/8990/standard-equation-for-steering-differential-drive-robot
    left = throttle + steer
    right = throttle - steer

    # Ensures that the motor values stay between -1 and 1.
    left = max(-1, min(1, left))
    right = max(-1, min(1, right))

    print("Left:", left, "Right:", right)

    #Use motor library to turn corresponding motors.    
    LEFT.throttle = left
    RIGHT.throttle = right

# Creates an mqtt client object that is able to talk to broker
mqtt_client = MQTT.MQTT(
    broker=MQTT_BROKER,
    port=MQTT_PORT,
    socket_pool=pool,
    ssl_context=ssl_context
)

#MQTT client is assigned the on_message function to know what happens when a message arrives
mqtt_client.on_message = on_message
try:
#   Try and connect to broker using client object
    mqtt_client.connect()
    print("MQTT connected!")
except Exception as e:
    print("MQTT connect failed:", e)
#Subscribe to the specific topics where the publisher sends commands
mqtt_client.subscribe(MQTT_TOPIC)

print("MQTT connected, waiting for commands...")

last_msg_time = time.monotonic()

#Keep the MQTT client running
while True:
    # Maintain the connection to the broker and process incoming messages
    mqtt_client.loop()

    # If no messages have been recieved for .5 seconds, stop all the motors
    if time.monotonic() - last_msg_time > 0.5:
        stop_all()
    #Provide a small delay to give the CPU some rest.
    time.sleep(0.01)
