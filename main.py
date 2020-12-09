#!/usr/bin/env python3

import tkinter as tk
from tkinter import font as tkfont
from tkinter.messagebox import showinfo
from PIL import Image, ImageTk
from enum import Enum
import RPi.GPIO as IO
import os
import cv2
import math
import logging
import requests
import grequests
import base64
import time
import datetime
import random
import queue
import threading

# module attached
IR_SENSOR_PIN = 5
LIGHT_SENSOR_LEFT_PIN = 14
LIGHT_SENSOR_RIGHT_PIN = 15
GATE_RELAY_PIN = 18

# main config
DIR_NAME = os.path.dirname(os.path.abspath(__file__))
API_URL = 'http://172.16.65.18:8989/api'
MACHINE = 'ESD-[Station]'
REQUEST_TIMEOUT = 1 #seconds
GATE_TIMEOUT = 7 #seconds
RECOGNIZE_TIMEOUT = 3 #seconds
CAMERA_TIMEOUT = 300 #seconds
BARCODE_SCAN_TIMEOUT = 10 #seconds
ESD_TEST_TIMEOUT = 7 #seconds

def setup_log(log_name, file_name, level=logging.INFO):
    dirname = os.path.dirname(file_name)
    if len(dirname) > 0 and not os.path.exists(dirname):
        os.makedirs(dirname)

    handler = logging.FileHandler(file_name, 'a', 'utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s : %(levelname)-8s - %(message)s'))

    logger = logging.getLogger(log_name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger

# logger
info_log = setup_log('info', DIR_NAME + '/logs/info.log', logging.INFO)
error_log = setup_log('error', DIR_NAME + '/logs/error.log', logging.ERROR)

class App(tk.Tk):

    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        IO.setwarnings(False)
        IO.setmode(IO.BCM)
        IO.setup(IR_SENSOR_PIN, IO.IN) #IR sensor
        IO.setup(LIGHT_SENSOR_LEFT_PIN, IO.IN) #Left light sensor
        IO.setup(LIGHT_SENSOR_RIGHT_PIN, IO.IN) #Right light sensor
        IO.setup(GATE_RELAY_PIN, IO.OUT) #Gate relay

        self.user = { "username": None, "fullname": None, "gender": None, "date_of_birth": None }
        self.test_type = None
        self.result = None
        self.new_input = False
        self.input_text = ""
        self.mode = AppMode.BARCODE_SCAN

        self.title("GUI")
        self.geometry("900x600")
        self.wm_attributes("-fullscreen", "true")
        # bind exit callback function
        self.protocol("WM_DELETE_WINDOW", self.quit)

        # the container is where we'll stack a bunch of frames
        # on top of each other, then the one we want visible
        # will be raised above the others
        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        # loop each page and add to frame
        for F in (MainPage, ConfigPage):
            page_name = F.__name__
            frame = F(parent=container, controller=self)
            self.frames[page_name] = frame

            # put all of the pages in the same location
            # the one on the top of the stacking order
            # will be the one that is visible
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("MainPage")
        self.bind('<Key>', self.read_key)

    def show_frame(self, page_name):
        '''Show a frame for the given page name'''
        frame = self.frames[page_name]
        frame.tkraise()

    def read_key(self, event):
        try:
            if event.keysym != 'Return':
                if self.input_text is None:
                    self.input_text = ""
                self.input_text += event.char
            else:
                self.user["username"] = self.input_text
                self.user["fullname"] = self.input_text
                self.input_text = ""
                self.new_input = True
                self.result = True
                self.test_type = "barcode"
                self.mode = AppMode.ESD_TEST
        except: pass

    def quit(self):
        self.mode = AppMode.QUIT
        # destroy each frame first 
        for frame in list(self.frames):
            del self.frames[frame]
        # destroy the app
        self.destroy()

class AppMode(Enum):
    IDLE = "ideal"
    MOTION_DETECT = "motion_detect"
    FACE_RECOGNIZE = "face_recognize"
    BARCODE_SCAN = "barcode_scan"
    ESD_TEST = "esd_test"
    QUIT = "quit"

class MainPage(tk.Frame):

    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller
        self.width = 900
        self.height = 600
        # timer for turning on/off camera
        self.cam_timer = Timer(1)
        # timer for each request will be sent to the server
        self.dur_timer = Timer()
        # timer for turning off camera when nothing detected
        self.face_timer = Timer(CAMERA_TIMEOUT)
        # the timeout for each face recognition
        self.recog_timer = Timer(RECOGNIZE_TIMEOUT)
        # the timeout for scanning barcode
        self.barcode_timer = Timer(BARCODE_SCAN_TIMEOUT)
        # the timeout for testing ESD
        self.esd_timer = Timer(ESD_TEST_TIMEOUT)
        # timer for refreshing GUI while idling
        self.refresh_timer = Timer()
        # the timeout for opening the gate
        self.gate_timer = Timer(GATE_TIMEOUT)
        # handle image queue
        self.req_queue = queue.Queue()
        # handle image thread
        self.req_thread = threading.Thread(target=self.observe_req_queue)
        self.recognizing = False
        self.data = { "title": "Welcome to Spartronics VN", "message": "Chúc bạn một ngày làm việc vui vẻ!" }
        self.camera_on = False
        self.left_foot = None
        self.right_foot = None
        self.esd_testing = False
        self.is_gate_opened = False
        # store all requests in a list and send to server interval time
        self.req_list = []
        # count the frame will be store in request list
        self.frame_count = 0

        image = Image.open(DIR_NAME + '/img/bg-image.png')
        image.putalpha(192)
        self.copy_image = image.copy()
        photo = ImageTk.PhotoImage(image)
        self.canvas = tk.Canvas(self)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind('<Configure>', self.resize_image)

        self.lmain = tk.Label(self.canvas, text="", font=(None, 20, "italic"), bg="white", fg="black")
        self.lmain.place(relx=0.005, rely=0, y=90, anchor="nw")
        #self.lbarcode = tk.Label(self.canvas, text="<Barcode>", font=(None, 50, "italic"), bg="gold", fg="black")
        #self.lbarcode.place(relx=1.0, rely=1.0, x=-5, y=-5, anchor="se")

        self.lmain.bind("<Button-1>", self.open_camera)
        #self.lbarcode.bind("<Button-1>", self.use_barcode)
        self.use_barcode()
        self.detect_motion()
        self.req_thread.start()

    def render(self):
        width = self.width
        height = self.height
        rs_image = self.copy_image.resize((self.width, self.height))
        photo = ImageTk.PhotoImage(rs_image)
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, image=photo, anchor="nw", tags="bg")
        self.canvas.image = photo #avoid garbage collection

        #self.canvas.create_text(width / 2, height / 6, text=self.data["title"], fill='red', font=("fixedsys",50,"bold"), anchor="n", tags="title")
        self.set_message(self.data["message"])
        #self.canvas.create_line(width / 3, height / 3, 2 * width / 3, height / 3)

    def render_card(self, rendered):
        if rendered == True and self.controller.mode == AppMode.BARCODE_SCAN:
            cardimg = Image.open(DIR_NAME + "/img/verify_card.jpg")
            cardimg = cardimg.resize((150,200))
            cardphoto = ImageTk.PhotoImage(cardimg)
            self.canvas.create_image(self.width/2-75, self.height-200, image=cardphoto, anchor="nw", tags="card")
            self.canvas.cardimage = cardphoto
        else:
            self.canvas.delete('card')
            self.canvas.cardimage = None

    def render_esd_result(self, rendered):
        self.canvas.delete('rfoot')
        self.canvas.delete('lfoot')

        if rendered == True and self.controller.mode == AppMode.ESD_TEST and self.left_foot is not None and self.right_foot is not None:
            pic_w = 200
            pic_h = 100
            pic_o = 10

            lfpic = DIR_NAME + "/img/left_" + ("passed" if self.left_foot else "failed") + ".png"
            lfimg = Image.open(lfpic)
            lfimg = lfimg.resize((pic_w, pic_h))
            lfphoto = ImageTk.PhotoImage(lfimg)
            self.canvas.create_image(self.width - pic_w * 2 - pic_o, self.height - pic_h - pic_o, image=lfphoto, anchor="nw", tags="lfoot")
            self.canvas.lfimg = lfphoto

            rtpic = DIR_NAME + "/img/right_" + ("passed" if self.right_foot else "failed") + ".png"
            rtimg = Image.open(rtpic)
            rtimg = rtimg.resize((pic_w, pic_h))
            rtphoto = ImageTk.PhotoImage(rtimg)
            self.canvas.create_image(self.width - pic_w - pic_o, self.height - pic_h - pic_o, image=rtphoto, anchor="nw", tags="rfoot")
            self.canvas.rtimg = rtphoto

    def detect_motion(self):
        if (IO.input(IR_SENSOR_PIN) == True):
            self.open_camera()
        self.close_gate()
        self.after(10, self.detect_motion)

    def open_camera(self, event=None):
        if (self.cam_timer.is_timeout()):
            if (self.camera_on == False):
                try:
                    self.capture = cv2.VideoCapture(0)
                    self.camera_on = True
                    self.face_timer.reset()
                    self.video_stream()
                    print('open camera ' + str(datetime.datetime.now()))
                except Exception as e:
                    self.camera_on = False
                    error_log.exception(e, exc_info=True)
                    if (self.controller.mode == AppMode.BARCODE_SCAN):
                        self.lmain.configure(text="<Camera Failed>", bg='red')
                        self.use_barcode()
        else:
            self.after(100, self.open_camera)

    def close_camera(self):
        print('close camera ' + str(datetime.datetime.now()))
        self.capture.release()
        self.cam_timer.reset()
        self.camera_on = False
        self.motion = False
        self.lmain.configure(image = "", text="", bg="white")
        self.lmain.imgtk = None
        self.refresh()

    def set_state_message(self):
        name = self.controller.user["fullname"]
        name = name if name is not None else ""
        switcher = {
            AppMode.IDLE: "Chúc bạn một ngày làm việc vui vẻ!",
            AppMode.FACE_RECOGNIZE: "Đang nhận diện...",
            AppMode.BARCODE_SCAN: "Chào mừng bạn đến với Spartronics VN!",
            AppMode.ESD_TEST: "Xin chào, " + name + "!\nMời bạn test ESD!"
        }
        self.set_message(switcher[self.controller.mode])
        self.render()

    def resize_image(self, event):
        self.width = event.width
        self.height = event.height
        self.render()

    def set_message(self, message):
        self.data["message"] = message
        self.canvas.delete('message')
        self.canvas.create_text(self.width / 3, self.height - 60, text=self.data["message"], fill='RoyalBlue4', font=("Times",32,"bold"), justify="center", anchor="center", tags="message")

    def refresh(self):
        if self.refresh_timer.is_timeout():
            # refresh application state if anyone tested
            if not self.esd_testing:
                self.controller.user = { "username": None, "fullname": None }
                self.controller.result = False
                self.left_foot = None
                self.right_foot = None
                self.controller.mode = AppMode.BARCODE_SCAN
                self.set_state_message()

            self.close_gate()
        else:
            self.after(1000, self.refresh)

    def open_gate(self):
        self.gate_timer.reset()
        self.is_gate_opened = True
        IO.output(GATE_RELAY_PIN, 1)

    def close_gate(self):
        if (self.gate_timer.is_timeout() and self.is_gate_opened):
            IO.output(GATE_RELAY_PIN, 0)
            self.is_gate_opened = False

    def authenticate(self, username):
        try:
            if username is None:
                return False

            res = requests.post(API_URL + '/esd/authenticate', { "username": username }, timeout=REQUEST_TIMEOUT)
            if (res.status_code == 401):
                self.set_message('Unauthorized ' + username)
                self.controller.user["username"] = None
                self.refresh_timer.set_interval(1)
                self.after(1000, self.refresh)
                return False
            elif (res.status_code == 200):
                json = res.json()
                self.controller.user["username"] = json["username"]
                self.controller.user["fullname"] = json["fullname"]
                self.controller.user["gender"] = json["gender"]
                self.controller.user["date_of_birth"] = json["date_of_birth"]
        except Exception as e:
            error_log.exception(e, exc_info=True)

        return True

    def handle_barcode(self):
        #self.render_card(True)
        if (self.controller.new_input and self.controller.user["username"] is not None):
            if self.authenticate(self.controller.user["username"]):
                self.test_esd()
                self.controller.new_input = False

        self.after(100, self.handle_barcode)

    def handle_esd_test(self):
        # return 0 if sensor detected light
        self.left_foot = not IO.input(LIGHT_SENSOR_LEFT_PIN)
        self.right_foot = not IO.input(LIGHT_SENSOR_RIGHT_PIN)

        self.render_esd_result(True)
        if (self.controller.user["username"] is not None):
            if (self.left_foot == True and self.right_foot == True and self.esd_timer.is_timeout(1)):

                if self.esd_testing:
                    self.esd_testing = False
                    # record passed result
                    self.save_result(self.controller.user["username"], self.controller.user["fullname"], self.controller.test_type, self.esd_timer.duration(), "passed")

                    self.set_message('Chúc bạn một ngày làm việc vui vẻ! ^_^')
                    self.open_gate()
                    self.refresh_timer.set_interval(3)
                    self.after(3000, self.refresh)

                return

        # wait for testing ESD
        if (self.esd_timer.is_timeout()):
            self.esd_testing = False
            # record failed result
            self.save_result(self.controller.user["username"], self.controller.user["fullname"], self.controller.test_type, self.esd_timer.duration(), "failed")

            # display message within 3 seconds and refresh UI
            self.set_message('Test thất bại! Mời bạn thử lại lần nữa!')
            self.controller.mode = AppMode.IDLE
            self.refresh_timer.set_interval(3)
            self.after(3000, self.refresh)
        else:
            self.after(100, self.handle_esd_test)

    def save_result(self, username, fullname, test_type, duration, result):
        data = {
            "username": username,
            "fullname": fullname,
            "type": test_type,
            "duration": duration,
            "result": result,
            "machine": MACHINE
        }

        # log the result
        info_log.info("{0}({1}) - mode:{2} - duration:{3} - result:{4} - machine:{5}".format(data["username"], data["fullname"], data["type"], data["duration"], data["result"], data["machine"]))
        # save the result
        try:
            requests.post(API_URL + '/esd/save', data, timeout=REQUEST_TIMEOUT)
        except:
            # local storage when save data to server failed
            self.save_file(data)

    def save_file(self, data):
        f = open(DIR_NAME + '/records.txt', 'a')
        f.write('{0},{1},{2},{3},{4},{5}\n'.format(data["username"], data["fullname"], data["type"], data["duration"], data["result"], data["machine"]))
        f.close()

    def video_stream(self):
        # read camera frame and display on screen
        _, frame = self.capture.read()
        cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # render image to screen
        img = Image.fromarray(cv2image)
        resized_img = img.resize((int(self.width * 0.99), int(self.height * 0.73)))
        imgtk = ImageTk.PhotoImage(image=resized_img)
        self.lmain.imgtk = imgtk
        self.lmain.configure(image=imgtk)
        self.lmain.update()

        if self.req_queue.empty():
            # put an function into queue, the function invokes handle method
            self.req_queue.put(lambda: self.handle_image(frame))

        # close camera if no any faces detected
        if (self.face_timer.is_timeout()):
            self.close_camera()
        # recall to stream video
        else:
            self.lmain.after(1, self.video_stream)

    def observe_req_queue(self):
        while True:
            try:
                if self.controller.mode == AppMode.QUIT:
                    break
                fn = self.req_queue.get()
                fn()
            except queue.Empty:
                break

        # observe the queue to handle until the application quit
        if self.controller.mode != AppMode.QUIT:
            self.lmain.after(100, self.observe_req_queue)

    def post_image(self, base64img):
        data = { "data": base64img }
        r = requests.post(url = API_URL + "/face", data = data, timeout=REQUEST_TIMEOUT)
        return r.json()

    def set_result(self, result, id, name):
        self.controller.result = result
        self.controller.user["username"] = id
        self.controller.user["fullname"] = name
        self.set_state_message()

    def use_barcode(self, event=None):
        self.recognizing = False
        self.controller.mode = AppMode.BARCODE_SCAN
        self.controller.test_type = "barcode"
        self.set_state_message()
        self.barcode_timer.reset()
        self.handle_barcode()

    def test_esd(self):
        self.controller.mode = AppMode.ESD_TEST
        self.set_state_message()
        self.esd_timer.reset()
        self.esd_testing = True
        self.handle_esd_test()

    def handle_image(self, imgframe):
        if (self.controller.mode != AppMode.ESD_TEST):
            try:
                self.frame_count += 1
                if (len(self.req_list) == 0 or self.frame_count % 2 == 0):
                    _, buf = cv2.imencode(".jpg", imgframe)
                    base64img = base64.b64encode(buf)
                    data = { "data": base64img }
                    self.req_list.append(grequests.post(url = API_URL + "/face", data = data, timeout=REQUEST_TIMEOUT))
                    self.frame_count = 0

                # sent request to server every 0.5 seconds
                if (self.dur_timer.is_timeout(0.1)):
                    # send image to server in order to detect face id
                    res = grequests.map(self.req_list, 10)
                    self.req_list.clear()
                    # sorted the response in ordered
                    sorted_res = sorted(res, key=lambda x: 3 if x is None else 0 if x.json()["result"] else 1 if x.json()["username"] is not None else 2)
                    if sorted_res[0] is not None:
                        json = sorted_res[0].json()
                    else:
                        json = { "result": False, "username": None }
                    if (json["result"] == True and json["username"] != self.controller.user["username"]):
                        self.controller.test_type = "face_id"
                        self.set_result(True, json["username"], json["fullname"])
                        if self.authenticate(self.controller.user["username"]):
                            self.test_esd()

                    # refresh face timer when there is a person detected
                    if (json["username"] is not None):
                        self.face_timer.reset()
                        if (self.recognizing == False and json["username"] == ""):
                            self.recognizing = True
                            self.recog_timer.reset()
                            self.controller.mode = AppMode.FACE_RECOGNIZE
                            self.set_state_message()

                    # timer reset every request posted
                    self.dur_timer.reset()

                # change to barcode sanner if recognition failed
                if (self.recognizing == True and self.recog_timer.is_timeout()):
                    self.use_barcode()
                    self.set_message('Mời bạn quét mã số')
                    self.refresh_timer.set_interval(3)
                    self.after(3000, self.refresh)
            except Exception as e:
                print(e)
                self.use_barcode()

class Timer():

    def __init__(self, interval=0):
        self.timer = time.time()
        self.interval = interval

    def set_interval(self, interval):
        self.interval = interval
        self.reset()

    def reset(self):
        self.timer = time.time()

    def duration(self):
        return round(time.time() - self.timer, 2)

    def is_timeout(self, seconds=None):
        interval = seconds if seconds is not None else self.interval
        return time.time() - self.timer > interval

class ConfigPage(tk.Frame):

    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller


if __name__ == "__main__":
    app = App()
    app.mainloop()
