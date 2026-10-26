import ctypes
import json
import math
import os
import sys
import threading
import time
import customtkinter as ctk
import vgamepad as vg
from pynput import keyboard, mouse

# Force immediate unbuffered console output
sys.stdout.reconfigure(line_buffering=True)

# ==============================================================================
# CONFIGURATION & CONSTANTS (PHASE 6)
# ==============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

DEFAULT_CONFIG = {
    "sensitivity": 0.055,       # High responsiveness for controller thumbstick look
    "anti_deadzone": 0.18,     # Overcomes game stick deadzones immediately
    "exponent": 0.85,          # Fine micro-aim + fast snap flicks
    "smoothing": 0.40,         # Anti-jitter filtering
    "invert_y": False,         # Normal (mouse-up = stick-up)
    "aim_only": False,         # Default False (Full Controller mode for Aim Assist)
    "always_on_top": True
}

# Live Parameters (Shared across threads)
params = {
    "sensitivity": DEFAULT_CONFIG["sensitivity"],
    "anti_deadzone": DEFAULT_CONFIG["anti_deadzone"],
    "exponent": DEFAULT_CONFIG["exponent"],
    "smoothing": DEFAULT_CONFIG["smoothing"],
    "invert_y": DEFAULT_CONFIG["invert_y"],
    "aim_only": DEFAULT_CONFIG["aim_only"],
    "always_on_top": DEFAULT_CONFIG["always_on_top"]
}

UPDATE_RATE_HZ = 120

# ==============================================================================
# WINDOWS API & HIGH-PRECISION TIMING
# ==============================================================================
user32 = ctypes.windll.user32
winmm = ctypes.windll.winmm

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

# ==============================================================================
# GLOBAL STATE & THREAD SYNCHRONIZATION
# ==============================================================================
is_active = False
running = True
app_instance = None

# Controller State
curr_lx = 0.0
curr_ly = 0.0
curr_rx = 0.0
curr_ry = 0.0
curr_lt = 0.0
curr_rt = 0.0

held_keys = set()
pressed_buttons = set()

# Low-level mouse hook tracking
last_mouse_x = None
last_mouse_y = None
accum_mouse_dx = 0
accum_mouse_dy = 0
mouse_delta_lock = threading.Lock()
gamepad_lock = threading.Lock()

# Listeners
kb_listener = None
mouse_listener = None

# Initialize Virtual Gamepad
try:
    gamepad = vg.VX360Gamepad()
    gamepad.reset()
    gamepad.update()
except Exception as e:
    print(f"ERROR: Could not initialize virtual controller: {e}", flush=True)
    sys.exit(1)

# Game-HUD Button Mappings
BUTTON_MAP = {
    'A': vg.XUSB_BUTTON.XUSB_GAMEPAD_A,              # Space (Jump)
    'B': vg.XUSB_BUTTON.XUSB_GAMEPAD_B,              # C / Left Shift (Slide)
    'X': vg.XUSB_BUTTON.XUSB_GAMEPAD_X,              # R (Reload)
    'Y': vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,              # 1, 2, 3 (Swap Weapons)
    'LB': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER, # Q (Ability 1)
    'RB': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,# E (Ability 2)
    'DPAD_UP': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,  # X (Ability 3 / Ultimate)
    'R3': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,   # F (Quick Melee)
}

# Windows Virtual Key Codes to Intercept & Suppress
VK_F8 = 0x77
VK_END = 0x23

VK_MAPPINGS = {
    ord('W'): 'w',
    ord('A'): 'a',
    ord('S'): 's',
    ord('D'): 'd',
    0x20: 'space',      # Space (Jump)
    ord('C'): 'c',      # C (Slide)
    0x10: 'shift',      # Shift
    0xA0: 'shift',      # Left Shift
    0xA1: 'shift',      # Right Shift
    ord('R'): 'r',      # R (Reload)
    ord('1'): '1',      # 1 (Swap Weapon)
    ord('2'): '2',      # 2 (Swap Weapon)
    ord('3'): '3',      # 3 (Swap Weapon)
    0x61: '1',          # Numpad 1
    0x62: '2',          # Numpad 2
    0x63: '3',          # Numpad 3
    ord('Q'): 'q',      # Q (Ability 1)
    ord('E'): 'e',      # E (Ability 2)
    ord('X'): 'x',      # X (Ultimate)
    ord('F'): 'f',      # F (Quick Melee)
}

# ==============================================================================
# CONFIG PERSISTENCE
# ==============================================================================
def load_config():
    global params
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    params[k] = saved.get(k, v)
            print(f"Loaded configuration from {CONFIG_FILE}")
        except Exception as e:
            print(f"Warning: Failed to load config.json: {e}")

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(params, f, indent=4)
        print(f"Saved configuration to {CONFIG_FILE}")
        return True
    except Exception as e:
        print(f"Error saving config.json: {e}")
        return False

# ==============================================================================
# CONTROLLER RESET & WAKE-UP
# ==============================================================================
def reset_all_inputs():
    """Resets all virtual buttons, triggers, and joysticks to neutral."""
    global curr_lx, curr_ly, curr_rx, curr_ry, curr_lt, curr_rt, held_keys, pressed_buttons
    global accum_mouse_dx, accum_mouse_dy, last_mouse_x, last_mouse_y
    with mouse_delta_lock:
        accum_mouse_dx = 0
        accum_mouse_dy = 0
        last_mouse_x = None
        last_mouse_y = None

    with gamepad_lock:
        held_keys.clear()
        pressed_buttons.clear()
        curr_lx = 0.0
        curr_ly = 0.0
        curr_rx = 0.0
        curr_ry = 0.0
        curr_lt = 0.0
        curr_rt = 0.0
        gamepad.reset()
        gamepad.update()

def send_controller_wakeup_pulse():
    """Sends a brief virtual gamepad pulse so Roblox switches HUD to Xbox controller badges."""
    def _pulse():
        time.sleep(0.04)
        with gamepad_lock:
            gamepad.left_joystick_float(0.0, 0.15)
            gamepad.update()
        time.sleep(0.06)
        with gamepad_lock:
            gamepad.left_joystick_float(0.0, 0.0)
            gamepad.update()
    threading.Thread(target=_pulse, daemon=True).start()

# ==============================================================================
# KEYBOARD INPUT HANDLERS (WASD & HUD ACTIONS)
# ==============================================================================
def update_keyboard_controller():
    global curr_lx, curr_ly

    if not is_active:
        return

    # In Aim-Only Mode, leave keyboard untouched
    if params["aim_only"]:
        if curr_lx != 0.0 or curr_ly != 0.0 or pressed_buttons:
            with gamepad_lock:
                curr_lx = 0.0
                curr_ly = 0.0
                gamepad.left_joystick_float(0.0, 0.0)
                for btn in list(pressed_buttons):
                    gamepad.release_button(button=BUTTON_MAP[btn])
                pressed_buttons.clear()
                gamepad.update()
        return

    # 1. WASD Left Joystick
    target_y = 0.0
    if 'w' in held_keys and 's' not in held_keys:
        target_y = 1.0
    elif 's' in held_keys and 'w' not in held_keys:
        target_y = -1.0

    target_x = 0.0
    if 'd' in held_keys and 'a' not in held_keys:
        target_x = 1.0
    elif 'a' in held_keys and 'd' not in held_keys:
        target_x = -1.0

    # Diagonal Normalization
    if target_x != 0.0 and target_y != 0.0:
        target_x /= 1.414
        target_y /= 1.414

    curr_lx = target_x
    curr_ly = target_y

    # 2. Action Buttons Mapping (Specific to Game HUD)
    desired_buttons = set()
    if 'space' in held_keys:
        desired_buttons.add('A')           # Jump
    if 'c' in held_keys or 'shift' in held_keys:
        desired_buttons.add('B')           # Slide
    if 'r' in held_keys:
        desired_buttons.add('X')           # Reload
    if '1' in held_keys or '2' in held_keys or '3' in held_keys:
        desired_buttons.add('Y')           # Swap Weapons
    if 'q' in held_keys:
        desired_buttons.add('LB')          # Ability 1
    if 'e' in held_keys:
        desired_buttons.add('RB')          # Ability 2
    if 'x' in held_keys:
        desired_buttons.add('DPAD_UP')     # Ability 3 / Ultimate
    if 'f' in held_keys:
        desired_buttons.add('R3')          # Quick Melee

    with gamepad_lock:
        gamepad.left_joystick_float(x_value_float=curr_lx, y_value_float=curr_ly)

        for btn in desired_buttons - pressed_buttons:
            gamepad.press_button(button=BUTTON_MAP[btn])
            pressed_buttons.add(btn)

        for btn in pressed_buttons - desired_buttons:
            gamepad.release_button(button=BUTTON_MAP[btn])
            pressed_buttons.remove(btn)

        gamepad.update()

# ==============================================================================
# LOW-LEVEL EVENT FILTERS (PROCESSED DIRECTLY BEFORE SUPPRESSION)
# ==============================================================================
def kb_event_filter(msg, data):
    """Processes key-down and key-up BEFORE suppression so controller state always updates."""
    global is_active, running
    vk = data.vkCode

    # 1. Kill-Switch: END (Never suppressed - instant safety exit)
    if vk == VK_END:
        if msg in (0x0100, 0x0104):
            print("[KILL-SWITCH] 'END' pressed! Exiting application...", flush=True)
            running = False
            is_active = False
            reset_all_inputs()
            if app_instance:
                app_instance.after(0, app_instance.destroy)
        return True

    # 2. Toggle Active/Paused: F8 (Never suppressed)
    if vk == VK_F8:
        if msg in (0x0100, 0x0104):
            is_active = not is_active
            reset_all_inputs()
            if is_active:
                send_controller_wakeup_pulse()
                print(">>> STATUS: [ACTIVE] - Physical inputs suppressed, Virtual Xbox engaged! <<<", flush=True)
            else:
                print(">>> STATUS: [PAUSED] - Normal Keyboard/Mouse restored. <<<", flush=True)
        return True

    # When PAUSED, let all keys pass through 100% normally
    if not is_active:
        return True

    # In Aim-Only mode, let keyboard keys pass through
    if params["aim_only"]:
        return True

    # 3. Mapped HUD Keys: Update Virtual Controller State, then Suppress
    if vk in VK_MAPPINGS:
        key_name = VK_MAPPINGS[vk]
        is_press = (msg in (0x0100, 0x0104))
        is_release = (msg in (0x0101, 0x0105))

        if is_press:
            held_keys.add(key_name)
        elif is_release:
            held_keys.discard(key_name)

        # UPDATE VIRTUAL CONTROLLER IMMEDIATELY BEFORE SUPPRESSING
        update_keyboard_controller()

        # Suppress physical key from reaching Windows or the game
        if kb_listener:
            kb_listener.suppress_event()

    # Unmapped keys (Esc, Enter, Tab, Chat, etc.) pass through normally
    return True

def mouse_event_filter(msg, data):
    """Processes mouse clicks & movement BEFORE suppression."""
    global curr_lt, curr_rt, accum_mouse_dx, accum_mouse_dy, last_mouse_x, last_mouse_y
    if not running or not is_active:
        return True

    # 1. Left Mouse Button (Shoot -> RT)
    if msg in (0x0201, 0x0202):  # WM_LBUTTONDOWN, WM_LBUTTONUP
        pressed = (msg == 0x0201)
        curr_rt = 1.0 if pressed else 0.0
        with gamepad_lock:
            gamepad.right_trigger_float(value_float=curr_rt)
            gamepad.update()
        if mouse_listener:
            mouse_listener.suppress_event()

    # 2. Right Mouse Button (Aim -> LT)
    elif msg in (0x0204, 0x0205):  # WM_RBUTTONDOWN, WM_RBUTTONUP
        pressed = (msg == 0x0204)
        curr_lt = 1.0 if pressed else 0.0
        with gamepad_lock:
            gamepad.left_trigger_float(value_float=curr_lt)
            gamepad.update()
        if mouse_listener:
            mouse_listener.suppress_event()

    # 3. Mouse Movement (Look -> Right Stick)
    elif msg == 0x0200:  # WM_MOUSEMOVE
        # Ignore synthetic cursor recentering
        if data.flags & 1:
            if mouse_listener:
                mouse_listener.suppress_event()
            return True

        if last_mouse_x is None:
            last_mouse_x = data.pt.x
            last_mouse_y = data.pt.y
            if mouse_listener:
                mouse_listener.suppress_event()
            return True

        dx = data.pt.x - last_mouse_x
        dy = data.pt.y - last_mouse_y
        last_mouse_x = data.pt.x
        last_mouse_y = data.pt.y

        with mouse_delta_lock:
            accum_mouse_dx += dx
            accum_mouse_dy += dy

        # Keep cursor bounded so physical mouse never hits monitor boundaries
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        if last_mouse_x < 60 or last_mouse_x > screen_w - 60 or last_mouse_y < 60 or last_mouse_y > screen_h - 60:
            center_x = screen_w // 2
            center_y = screen_h // 2
            user32.SetCursorPos(center_x, center_y)
            last_mouse_x = center_x
            last_mouse_y = center_y

        # Suppress physical mouse movement from reaching the game window
        if mouse_listener:
            mouse_listener.suppress_event()

    return True

# ==============================================================================
# MOUSE AIM LOOP (120Hz HIGH-PRECISION THREAD)
# ==============================================================================
def calculate_right_stick(dx, dy, prev_rx, prev_ry):
    """Calculates smoothed Right Analog Stick coordinates from mouse delta."""
    input_x = float(dx)
    if params["invert_y"]:
        input_y = float(dy)
    else:
        input_y = float(-dy)

    mag = math.hypot(input_x, input_y)

    if mag == 0.0:
        decay_rx = prev_rx * 0.2
        decay_ry = prev_ry * 0.2
        if abs(decay_rx) < 0.02 and abs(decay_ry) < 0.02:
            return 0.0, 0.0
        return decay_rx, decay_ry

    nx = input_x / mag
    ny = input_y / mag

    scaled = mag * params["sensitivity"]
    powered = math.pow(scaled, params["exponent"])

    ad = params["anti_deadzone"]
    output_mag = ad + (1.0 - ad) * powered
    output_mag = min(1.0, max(0.0, output_mag))

    raw_rx = nx * output_mag
    raw_ry = ny * output_mag

    sm = params["smoothing"]
    smoothed_rx = prev_rx * sm + raw_rx * (1.0 - sm)
    smoothed_ry = prev_ry * sm + raw_ry * (1.0 - sm)

    final_mag = math.hypot(smoothed_rx, smoothed_ry)
    if final_mag > 1.0:
        smoothed_rx /= final_mag
        smoothed_ry /= final_mag

    return smoothed_rx, smoothed_ry

def mouse_aim_worker():
    global curr_rx, curr_ry
    tick_interval = 1.0 / UPDATE_RATE_HZ
    winmm.timeBeginPeriod(1)

    try:
        while running:
            if not is_active:
                time.sleep(0.016)
                continue

            with mouse_delta_lock:
                dx = accum_mouse_dx
                dy = accum_mouse_dy
                accum_mouse_dx = 0
                accum_mouse_dy = 0

            new_rx, new_ry = calculate_right_stick(dx, dy, curr_rx, curr_ry)

            if round(new_rx, 3) != round(curr_rx, 3) or round(new_ry, 3) != round(curr_ry, 3):
                curr_rx = new_rx
                curr_ry = new_ry
                with gamepad_lock:
                    if is_active:
                        gamepad.right_joystick_float(x_value_float=curr_rx, y_value_float=curr_ry)
                        gamepad.update()

            time.sleep(tick_interval)
    finally:
        winmm.timeEndPeriod(1)

# ==============================================================================
# MODERN DARK-MODE CUSTOMTKINTER GUI
# ==============================================================================
class ControllerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        global app_instance
        app_instance = self

        load_config()

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.title("KBM-to-XInput Virtual Controller")
        self.geometry("540x780")
        self.resizable(False, False)

        # Set Always on Top from config
        self.attributes('-topmost', params["always_on_top"])

        # Handle window close button
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.create_widgets()
        self.start_background_threads()
        self.update_telemetry()

    def create_widgets(self):
        # 1. Top Status Banner
        self.status_frame = ctk.CTkFrame(self, corner_radius=12, border_width=2)
        self.status_frame.pack(fill="x", padx=16, pady=(16, 10))

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="STATUS: PAUSED (Press F8)",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.status_label.pack(pady=(12, 4))

        self.substatus_label = ctk.CTkLabel(
            self.status_frame,
            text="[F8] Toggle Active/Paused   |   [END] Emergency Kill-Switch",
            font=ctk.CTkFont(size=11),
            text_color="#A0A0A0"
        )
        self.substatus_label.pack(pady=(0, 10))

        # 2. Mode & Safety Controls Frame
        self.mode_frame = ctk.CTkFrame(self, corner_radius=10)
        self.mode_frame.pack(fill="x", padx=16, pady=6)

        # Aim-Only Hybrid Mode Switch
        self.aim_only_var = ctk.BooleanVar(value=params["aim_only"])
        self.aim_only_switch = ctk.CTkSwitch(
            self.mode_frame,
            text="Aim-Only Mode (Mouse -> Right Stick Only)",
            variable=self.aim_only_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_aim_only_toggle
        )
        self.aim_only_switch.pack(anchor="w", padx=16, pady=(12, 2))

        self.aim_hint_label = ctk.CTkLabel(
            self.mode_frame,
            text="Unchecked = Full Controller Mode (Suppresses physical KBM for Aim Assist)",
            font=ctk.CTkFont(size=10),
            text_color="#888888"
        )
        self.aim_hint_label.pack(anchor="w", padx=16, pady=(0, 10))

        # Checkboxes row (Always on Top & Invert Y)
        cb_row = ctk.CTkFrame(self.mode_frame, fg_color="transparent")
        cb_row.pack(fill="x", padx=16, pady=(0, 12))

        self.topmost_var = ctk.BooleanVar(value=params["always_on_top"])
        self.topmost_cb = ctk.CTkCheckBox(
            cb_row,
            text="Always on Top",
            variable=self.topmost_var,
            command=self.on_topmost_toggle
        )
        self.topmost_cb.pack(side="left", padx=(0, 24))

        self.invert_y_var = ctk.BooleanVar(value=params["invert_y"])
        self.invert_y_cb = ctk.CTkCheckBox(
            cb_row,
            text="Invert Y-Axis",
            variable=self.invert_y_var,
            command=self.on_invert_y_toggle
        )
        self.invert_y_cb.pack(side="left")

        # 3. Tuning Sliders Frame
        self.sliders_frame = ctk.CTkFrame(self, corner_radius=10)
        self.sliders_frame.pack(fill="x", padx=16, pady=6)

        slider_title = ctk.CTkLabel(
            self.sliders_frame,
            text="Mouse Aim & Curve Tuning",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        slider_title.pack(anchor="w", padx=16, pady=(10, 8))

        # Slider: Sensitivity (0.005 to 0.150)
        self.sens_label = ctk.CTkLabel(self.sliders_frame, text=f"Sensitivity: {params['sensitivity']:.3f}", font=ctk.CTkFont(size=12))
        self.sens_label.pack(anchor="w", padx=16, pady=(2, 0))
        self.sens_slider = ctk.CTkSlider(self.sliders_frame, from_=0.005, to=0.150, number_of_steps=145, command=self.on_sens_change)
        self.sens_slider.set(params["sensitivity"])
        self.sens_slider.pack(fill="x", padx=16, pady=(0, 8))

        # Slider: Anti-Deadzone Boost (0.00 to 0.35)
        self.deadzone_label = ctk.CTkLabel(self.sliders_frame, text=f"Anti-Deadzone Boost: {params['anti_deadzone']:.2f}", font=ctk.CTkFont(size=12))
        self.deadzone_label.pack(anchor="w", padx=16, pady=(2, 0))
        self.deadzone_slider = ctk.CTkSlider(self.sliders_frame, from_=0.00, to=0.35, number_of_steps=35, command=self.on_deadzone_change)
        self.deadzone_slider.set(params["anti_deadzone"])
        self.deadzone_slider.pack(fill="x", padx=16, pady=(0, 8))

        # Slider: Response Curve / Exponent (0.40 to 1.50)
        self.expo_label = ctk.CTkLabel(self.sliders_frame, text=f"Response Exponent: {params['exponent']:.2f}", font=ctk.CTkFont(size=12))
        self.expo_label.pack(anchor="w", padx=16, pady=(2, 0))
        self.expo_slider = ctk.CTkSlider(self.sliders_frame, from_=0.40, to=1.50, number_of_steps=110, command=self.on_expo_change)
        self.expo_slider.set(params["exponent"])
        self.expo_slider.pack(fill="x", padx=16, pady=(0, 8))

        # Slider: Smoothing (0.00 to 0.85)
        self.smooth_label = ctk.CTkLabel(self.sliders_frame, text=f"Smoothing (Anti-Jitter): {params['smoothing']:.2f}", font=ctk.CTkFont(size=12))
        self.smooth_label.pack(anchor="w", padx=16, pady=(2, 0))
        self.smooth_slider = ctk.CTkSlider(self.sliders_frame, from_=0.00, to=0.85, number_of_steps=85, command=self.on_smooth_change)
        self.smooth_slider.set(params["smoothing"])
        self.smooth_slider.pack(fill="x", padx=16, pady=(0, 12))

        # 4. Live Telemetry Frame (No text clipping)
        self.telemetry_frame = ctk.CTkFrame(self, corner_radius=10)
        self.telemetry_frame.pack(fill="x", padx=16, pady=6)

        telem_title = ctk.CTkLabel(
            self.telemetry_frame,
            text="Live Virtual Controller Telemetry",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        telem_title.pack(anchor="w", padx=14, pady=(8, 4))

        self.stick_telem_label = ctk.CTkLabel(
            self.telemetry_frame,
            text="Left Stick (LS):  X:  0.00   Y:  0.00   |   Right Stick (RS):  X:  0.00   Y:  0.00",
            font=ctk.CTkFont(family="Consolas", size=11)
        )
        self.stick_telem_label.pack(anchor="w", padx=14, pady=2)

        self.trigger_telem_label = ctk.CTkLabel(
            self.telemetry_frame,
            text="Triggers:  LT: 0.0   RT: 0.0   |   Active Buttons: None",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#88C0D0"
        )
        self.trigger_telem_label.pack(anchor="w", padx=14, pady=(0, 10))

        # 5. Bottom Actions Frame (Save Settings)
        action_row = ctk.CTkFrame(self, fg_color="transparent")
        action_row.pack(fill="x", padx=16, pady=(8, 12))

        self.save_btn = ctk.CTkButton(
            action_row,
            text="Save Settings (config.json)",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_save_settings,
            height=36
        )
        self.save_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.save_status_label = ctk.CTkLabel(
            action_row,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00E676"
        )
        self.save_status_label.pack(side="right")

    # Slider & Checkbox Callbacks
    def on_sens_change(self, val):
        params["sensitivity"] = round(float(val), 3)
        self.sens_label.configure(text=f"Sensitivity: {params['sensitivity']:.3f}")

    def on_deadzone_change(self, val):
        params["anti_deadzone"] = round(float(val), 2)
        self.deadzone_label.configure(text=f"Anti-Deadzone Boost: {params['anti_deadzone']:.2f}")

    def on_expo_change(self, val):
        params["exponent"] = round(float(val), 2)
        self.expo_label.configure(text=f"Response Exponent: {params['exponent']:.2f}")

    def on_smooth_change(self, val):
        params["smoothing"] = round(float(val), 2)
        self.smooth_label.configure(text=f"Smoothing (Anti-Jitter): {params['smoothing']:.2f}")

    def on_aim_only_toggle(self):
        params["aim_only"] = self.aim_only_var.get()
        if params["aim_only"]:
            reset_all_inputs()

    def on_topmost_toggle(self):
        params["always_on_top"] = self.topmost_var.get()
        self.attributes('-topmost', params["always_on_top"])

    def on_invert_y_toggle(self):
        params["invert_y"] = self.invert_y_var.get()

    def on_save_settings(self):
        if save_config():
            self.save_status_label.configure(text="Saved!")
            self.after(2000, lambda: self.save_status_label.configure(text=""))

    def update_telemetry(self):
        # Update Status Banner Colors & Text
        if is_active:
            self.status_frame.configure(fg_color="#102E1B", border_color="#00E676")
            self.status_label.configure(text="STATUS: ACTIVE (Physical KBM Suppressed)", text_color="#00E676")
        else:
            self.status_frame.configure(fg_color="#2E1414", border_color="#FF4B4B")
            self.status_label.configure(text="STATUS: PAUSED (Press F8)", text_color="#FF4B4B")

        # Update Telemetry Labels
        lx_str = f"{curr_lx:5.2f}"
        ly_str = f"{curr_ly:5.2f}"
        rx_str = f"{curr_rx:5.2f}"
        ry_str = f"{curr_ry:5.2f}"
        self.stick_telem_label.configure(
            text=f"Left Stick (LS):  X: {lx_str}   Y: {ly_str}   |   Right Stick (RS):  X: {rx_str}   Y: {ry_str}"
        )

        btn_str = ", ".join(sorted(pressed_buttons)) if pressed_buttons else "None"
        self.trigger_telem_label.configure(
            text=f"Triggers:  LT: {curr_lt:.1f}   RT: {curr_rt:.1f}   |   Active Buttons: {btn_str}"
        )

        if running:
            self.after(50, self.update_telemetry)

    def start_background_threads(self):
        global kb_listener, mouse_listener

        # 120Hz Precision Aim Thread
        self.aim_thread = threading.Thread(target=mouse_aim_worker, daemon=True)
        self.aim_thread.start()

        # Low-level Windows Hook Listeners
        kb_listener = keyboard.Listener(win32_event_filter=kb_event_filter)
        kb_listener.start()

        mouse_listener = mouse.Listener(win32_event_filter=mouse_event_filter)
        mouse_listener.start()

    def on_closing(self):
        global running, is_active
        running = False
        is_active = False
        reset_all_inputs()
        try:
            if kb_listener:
                kb_listener.stop()
            if mouse_listener:
                mouse_listener.stop()
        except Exception:
            pass
        self.destroy()

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
def main():
    print("="*65, flush=True)
    print("  KBM-to-XInput Virtual Controller: Phase 6 GUI Active", flush=True)
    print("="*65, flush=True)
    print("Default Controls:")
    print("  [F8]   : Toggle Active / Paused (Suppresses physical inputs)")
    print("  [END]  : Emergency Kill-Switch & Exit")
    print("="*65 + "\n", flush=True)

    app = ControllerApp()
    app.mainloop()

if __name__ == "__main__":
    main()
