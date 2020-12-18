import serial
import threading

s = serial.Serial('/dev/ttyUSB0', 9600)
quit = False

def handle_data(data):
    print(data)

def read_port(s):
    while not quit:
        data = ''
        while not quit:
            length = s.inWaiting()
            if length > 0:
                buf = s.read().decode()
                if buf == '\n':
                    handle_data(data)
                    data = ''
                else:
                    data = data + buf
    
thread = threading.Thread(target=read_port, args=(s,))
thread.start()

while True:
    c = input()

    if c == 'q':
        print('quit')
        quit = True
        break

    s.write(str.encode(c))

quit = True
