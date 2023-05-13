# flask --app openscan.py run --host=0.0.0.0
from flask import Flask, request, jsonify, send_from_directory

import uuid
import threading
import json
import subprocess
import RPi.GPIO as GPIO

TMP_IMG_DIR = "/tmp/pic-openscan-asdf1234"

class OpenScanRobot(object):
    ROTOR_ANGLE_MAX = 115

    _ringlight_on = True
    _should_home = True
    _rotor_angle = 0
    _turntable_angle = 0

    _movement_stop_event = threading.Event()
    
    @staticmethod
    def init_app(app):
        RINGLIGHT1_PIN = 17
        RINGLIGHT2_PIN = 27
        
        ROTOR_DIR_PIN = 5
        ROTOR_STEP_PIN = 6
        ROTOR_ENABLE_PIN = 23
        ROTOR_STEPS_PER_ROTATION = 48000
        
        TURNTABLE_DIR_PIN = 9
        TURNTABLE_STEP_PIN = 11
        TURNTABLE_ENABLE_PIN = 22
        TURNTABLE_STEPS_PER_ROTATION = 3200

        # initialize the GPIO pins to the corrrect modes
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(RINGLIGHT1_PIN, GPIO.OUT)
        GPIO.setup(RINGLIGHT2_PIN, GPIO.OUT)
        GPIO.setup(ROTOR_DIR_PIN, GPIO.OUT)
        GPIO.setup(ROTOR_STEP_PIN, GPIO.OUT)
        GPIO.setup(ROTOR_ENABLE_PIN, GPIO.OUT)
        GPIO.setup(TURNTABLE_DIR_PIN, GPIO.OUT)
        GPIO.setup(TURNTABLE_STEP_PIN, GPIO.OUT)
        GPIO.setup(TURNTABLE_ENABLE_PIN, GPIO.OUT)
        
        def update_robot_state_background_thread_runner():
            stepper_pulse_event = threading.Event()
            STEPPER_PULSE_DELAY_HOME = 0.0001
            STEPPER_PULSE_DELAY_NORMAL = 0.0006
            
            GPIO.output(ROTOR_ENABLE_PIN, GPIO.HIGH)
            GPIO.output(TURNTABLE_ENABLE_PIN, GPIO.HIGH)
            actual_rotor_step_count = 0
            actual_turntable_step_count = 0

            def home_rotor():
                GPIO.output(ROTOR_DIR_PIN, GPIO.HIGH)
                for x in range(int((ROTOR_STEPS_PER_ROTATION*OpenScanRobot.ROTOR_ANGLE_MAX)/360)):
                    GPIO.output(ROTOR_STEP_PIN, GPIO.LOW)
                    stepper_pulse_event.wait(timeout=STEPPER_PULSE_DELAY_HOME)
                    GPIO.output(ROTOR_STEP_PIN, GPIO.HIGH)
                    stepper_pulse_event.wait(timeout=STEPPER_PULSE_DELAY_HOME)
                    actual_rotor_step_count = 0
            
            while True:
                GPIO.output(ROTOR_STEP_PIN, GPIO.LOW)
                GPIO.output(TURNTABLE_STEP_PIN, GPIO.LOW)
                    
                GPIO.output(RINGLIGHT1_PIN, OpenScanRobot._ringlight_on)
                GPIO.output(RINGLIGHT2_PIN, OpenScanRobot._ringlight_on)
                
                if OpenScanRobot._should_home:
                    OpenScanRobot._should_home = False
                    home_rotor()
                
                # Figure out how far to move each motor
                rotor_step_move = actual_rotor_step_count - int((ROTOR_STEPS_PER_ROTATION*OpenScanRobot._rotor_angle)/360)
                turntable_step_move = actual_turntable_step_count - int((TURNTABLE_STEPS_PER_ROTATION*OpenScanRobot._turntable_angle)/360)

                if not (rotor_step_move or turntable_step_move):
                    # Set the stop event if there will be no movement
                    OpenScanRobot._movement_stop_event.set()
                    
                    # since we aren't sending pulses wait a bit longer than normal before restarting runloop.
                    stepper_pulse_event.wait(timeout=0.01)
                    continue

                # Set the direction pin before sending the stepper pulses
                GPIO.output(ROTOR_DIR_PIN, GPIO.HIGH if rotor_step_move > 0 else GPIO.LOW)
                GPIO.output(TURNTABLE_DIR_PIN, GPIO.HIGH if turntable_step_move > 0 else GPIO.LOW)
                
                # Delay to make sure LOW stepper pin state is registered by stepper controller
                stepper_pulse_event.wait(timeout=STEPPER_PULSE_DELAY_NORMAL)
                
                # Set the stepper pin HIGH if movement is needed
                if rotor_step_move:
                    GPIO.output(ROTOR_STEP_PIN, GPIO.HIGH)
                    actual_rotor_step_count += -1 if rotor_step_move > 0 else 1
                if turntable_step_move:
                    GPIO.output(TURNTABLE_STEP_PIN, GPIO.HIGH)
                    actual_turntable_step_count += -1 if turntable_step_move > 0 else 1

                
                # Delay to make sure HIGH stepper pin state is registered by stepper controller
                stepper_pulse_event.wait(timeout=STEPPER_PULSE_DELAY_NORMAL)
        
        # Start the background thread where the robot state will be updated from.
        thread = threading.Thread(target=update_robot_state_background_thread_runner, args=())
        thread.start()
        
        return app

    @staticmethod
    def ringlight(state: bool):
        OpenScanRobot._ringlight_on = state

    @staticmethod
    def rotor(angle: float):
        tollerance = 5.0 # Stay away from where the gear disengages from the track
        if angle < tollerance:
            angle = tollerance
        if angle > OpenScanRobot.ROTOR_ANGLE_MAX - tollerance:
            angle = OpenScanRobot.ROTOR_ANGLE_MAX - tollerance
        OpenScanRobot._rotor_angle = angle


    @staticmethod
    def turntable(angle: float):
        OpenScanRobot._turntable_angle += angle

    @staticmethod
    def home():
        OpenScanRobot._should_home = True

    @staticmethod
    def wait_for_movement_to_stop():
        # Clear the movement_stop event so something will have to set it to not wait 
        OpenScanRobot._movement_stop_event.clear()
        
        # Wait as long as needed for the motors to stop
        OpenScanRobot._movement_stop_event.wait()


class Server(object):
    @staticmethod
    def create_app():
        app = Flask(__name__)
        subprocess.run(["mkdir", TMP_IMG_DIR])
        OpenScanRobot.init_app(app)
        return app

app = Server.create_app()

@app.route('/apiv1/ringlight', methods = ['POST'])
def rightlight_on():
    json_request = json.loads(request.data.decode('utf-8'))
    OpenScanRobot.ringlight(json_request["light_on"])
    return "{}"

@app.route('/apiv1/rotor', methods = ['POST'])
def rotor():
    json_request = json.loads(request.data.decode('utf-8'))
    OpenScanRobot.rotor(json_request["angle"])
    return "{}"

@app.route('/apiv1/turntable', methods = ['POST'])
def turntable():
    json_request = json.loads(request.data.decode('utf-8'))
    OpenScanRobot.turntable(json_request["angle_change"])
    return "{}"

@app.route('/apiv1/home_rotor', methods = ['POST'])
def home_rotor():
    OpenScanRobot.home()
    return "{}"

_camera_in_use_lock = threading.Lock()
@app.route('/apiv1/take_picture', methods = ['POST'])
def take_picture():
    json_request = json.loads(request.data.decode('utf-8'))
    OpenScanRobot.wait_for_movement_to_stop()
    base_filename = uuid.uuid4()
    cmd_args = ["libcamera-still", "--immediate", "--output", f'{TMP_IMG_DIR}/{base_filename}.jpg']
    download_files = [f'/download/{base_filename}.jpg']
    if "capture_dng" in json_request and json_request["capture_dng"]:
        cmd_args += ["--rawfull", "--raw"]
        download_files.append(f'/download/{base_filename}.dng')

    if "lens_position" in json_request:
        cmd_args += ["--lens-position", str(json_request["lens_position"])]

    if "shutter" in json_request:
        cmd_args += ["--shutter", str(json_request["shutter"])]
    with _camera_in_use_lock:
        subprocess.run(cmd_args, text=True)
    
    subprocess.run(["ln", "-f", "-s", f'{TMP_IMG_DIR}/{base_filename}.jpg', f'{TMP_IMG_DIR}/latest.jpg'])
    subprocess.run(["ln", "-f", "-s", f'{TMP_IMG_DIR}/{base_filename}.dng', f'{TMP_IMG_DIR}/latest.dng'])
    
    return jsonify(files=download_files)

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(TMP_IMG_DIR, filename)

# Super simple website that lets you see the last image taken and some curl commands to control cruft.
@app.route('/')
def hello_world():
    return """<!DOCTYPE html>
<html>
<body>
<img style="width:100%;max-width:750px" src="/download/latest.jpg" id="latest_img" alt="run the take_picture API to get an image here. This will show the latest image taken.">
<script>setInterval(() => {document.getElementById('latest_img').src = '/download/latest.jpg?rand=' + Math.random()},2000);</script>
<div>
<h2>Try these</h2>
<code>curl --header "Content-Type: application/json" --request POST --data '{"angle_change":10}' <script type="text/javascript">document.write(window.location.protocol + "//" + window.location.host);</script>/apiv1/turntable</code><br><br>
<code>curl --header "Content-Type: application/json" --request POST --data '{"angle":60}' <script type="text/javascript">document.write(window.location.protocol + "//" + window.location.host);</script>/apiv1/rotor</code><br><br>
<code>curl --header "Content-Type: application/json" --request POST --data '{"light_on":false}' <script type="text/javascript">document.write(window.location.protocol + "//" + window.location.host);</script>/apiv1/ringlight</code><br><br>
<code>curl --header "Content-Type: application/json" --request POST --data '{}' <script type="text/javascript">document.write(window.location.protocol + "//" + window.location.host);</script>/apiv1/home_rotor</code><br><br>
<code>curl --header "Content-Type: application/json" --request POST --data '{"capture_dng":true, "lens_position":200, "shutter":10000}' <script type="text/javascript">document.write(window.location.protocol + "//" + window.location.host);</script>/apiv1/take_picture</code><br><br>
</div>
</script>
</body>
</html>"""
