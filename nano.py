import serial
import re
import time
import threading

s = serial.Serial('/dev/ttyUSB0', 9600)
t = time.time()

class EsdNano:

    def __init__(self, port, timeout=2):
        self.nano = serial.Serial(port, 9600)
        self.reading = True
        self.connected = False
        self.left_foot = False
        self.right_foot = False
        self.thread = threading.Thread(target=self.read_from_port, args=(self.nano,))
        self.thread.start()

        timer = time.time()
        # waiting for the device response
        while not self.connected and int(time.time() - timer) < timeout:
            pass

        print("Connection to", port, end=" ")
        if not self.connected:
            self.reading = False
            print("timeout!")
        else:
            print("successful!")

    def is_connected(self):
        return self.connected

    def write(self, data):
        self.nano.write(str.encode(data))

    def begin_test(self):
        self.write('T')
    
    def end_test(self):
        self.write('E')

    def read_left_foot(self):
        return self.left_foot

    def read_right_foot(self):
        return self.right_foot 

    def trigger_gate(self, duration):
        self.write(f'O,{duration}')

    def handle_data(self, data):
        if "Connected" in data:
            self.connected = True

        # pattern for testing two foot
        matches = re.match('(L.),(R.)', data)
        if matches:
            # pattern matched the LP means Left Passed
            self.left_foot = matches.groups()[0] == "LP"
            # pattern matched the RP means Right Passed
            self.right_foot = matches.groups()[1] == "RP"
        else:
            self.left_foot = False
            self.right_foot = False

    def read_from_port(self, ser):
        data = str()
        while self.reading:
            try:
                # get number of characters left from buffer
                buf = ser.inWaiting()
                c = str()
                if buf > 0:
                    # read one character each time
                    c = ser.read().decode()
                    # handle data if character is end of the line
                    if c == '\n':
                        self.handle_data(data)
                        data = str()
                    else:
                        data = data + c
            except:
                pass

    def disconnect(self):
        self.reading = False 
        self.connected = False

    def __del__(self):
        self.disconnect()

if __name__ == "__main__":
    nano = EsdNano('/dev/ttyUSB0')
    print("Before testing")
    print(nano.read_left_foot())
    print(nano.read_right_foot())
    print("Begin testing")
    nano.begin_test()
    time.sleep(2)
    print(nano.read_left_foot())
    print(nano.read_right_foot())
    print("Trigger gate in 5 secs")
    nano.trigger_gate(5)
    time.sleep(2)
    print("Test after 2 secs")
    print(nano.read_left_foot())
    print(nano.read_right_foot())

    nano.disconnect()
    print("Disconnected")

