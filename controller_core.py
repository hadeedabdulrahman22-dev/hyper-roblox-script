"""
KBM-to-XInput engine (shared by app.py).

Turns keyboard + mouse into a virtual Xbox 360 controller so games that give
controller aim assist (e.g. Roblox shooters) treat you as a controller player.

Hotkeys (always work, never blocked):
    F8  - toggle Active / Paused
    END - emergency kill-switch (closes the app)
"""
import ctypes
import json
import math
import os
import sys
import tempfile
import threading
import time
import traceback
from ctypes import wintypes

if sys.platform != "win32":
    raise RuntimeError("This tool only runs on Windows.")

# Must run before any window exists so Windows reports true pixel coordinates
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import vgamepad as vg  # noqa: E402
from pynput import keyboard, mouse  # noqa: E402

# ==============================================================================
# SETTINGS
# ==============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
UPDATE_RATE_HZ = 120
CURSOR_DRIFT_LIMIT_PX = 150

DEFAULT_CONFIG = {
    "sensitivity": 0.055,       # mouse pixels -> stick strength
    "anti_deadzone": 0.18,      # jump past the game's stick deadzone instantly
    "exponent": 0.85,           # <1 = more reactive to small movements
    "smoothing": 0.40,          # anti-jitter (0 = raw, higher = smoother)
    "invert_y": False,
    "aim_only": False,          # True = only mouse -> right stick, keyboard untouched
    "block_mouse_move": True,   # True = freeze physical cursor via hook suppression
    "always_on_top": True,
}

LIMITS = {
    "sensitivity": (0.005, 0.150),
    "anti_deadzone": (0.00, 0.35),
    "exponent": (0.40, 1.50),
    "smoothing": (0.00, 0.85),
}

# ==============================================================================
# WINDOWS CONSTANTS & API SETUP
# ==============================================================================
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
LLMHF_INJECTED = 0x01

VK_F8 = 0x77
VK_END = 0x23

user32 = ctypes.windll.user32
winmm = ctypes.windll.winmm
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]

# Physical key -> logical key name
VK_TO_KEY = {
    ord("W"): "w", ord("A"): "a", ord("S"): "s", ord("D"): "d",
    0x20: "space",
    ord("C"): "c",
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    ord("R"): "r",
    ord("V"): "v",
    ord("1"): "1", ord("2"): "2", ord("3"): "3",
    0x61: "1", 0x62: "2", 0x63: "3",   # numpad 1-3
    ord("Q"): "q", ord("E"): "e", ord("X"): "x", ord("F"): "f",
}

# Controller button -> logical keys that press it (matched to Hypershot Controller HUD)
BUTTON_BINDINGS = {
    "A": {"space"},              # Jump -> A
    "B": {"x"},                  # Ability 3 (Ultimate) -> B
    "X": {"r", "v"},             # Reload / Inspect -> X
    "Y": {"1", "2"},             # Swap Weapons (Primary/Secondary) -> Y
    "LB": {"q"},                 # Ability 1 -> LB / L1
    "RB": {"e"},                 # Ability 2 -> RB / R1
    "DPAD_UP": {"3"},            # Knife / Melee Equip (Slot 3) -> DPAD_UP
    "L3": {"c", "shift"},        # Slide -> L3 (Left Stick Click)
    "R3": {"f"},                 # Quick Melee -> R3 (Right Stick Click)
}

BUTTON_MAP = {
    "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "DPAD_UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "L3": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "R3": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
}

DIAGONAL = 0.7071


# ==============================================================================
# XINPUT SLOT DETECTION
# ==============================================================================
def get_connected_xinput_slot():
    """Returns the connected XInput slot index (0-3) if connected, or None."""
    class XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [
            ("wButtons", wintypes.WORD),
            ("bLeftTrigger", wintypes.BYTE),
            ("bRightTrigger", wintypes.BYTE),
            ("sThumbLX", wintypes.SHORT),
            ("sThumbLY", wintypes.SHORT),
            ("sThumbRX", wintypes.SHORT),
            ("sThumbRY", wintypes.SHORT),
        ]

    class XINPUT_STATE(ctypes.Structure):
        _fields_ = [
            ("dwPacketNumber", wintypes.DWORD),
            ("Gamepad", XINPUT_GAMEPAD),
        ]

    for dll_name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
        try:
            xi = ctypes.windll.LoadLibrary(dll_name)
            state = XINPUT_STATE()
            for slot in range(4):
                if xi.XInputGetState(slot, ctypes.byref(state)) == 0:
                    return slot
        except Exception:
            continue
    return None


# ==============================================================================
# AIM MATH
# ==============================================================================
def compute_right_stick(dx, dy, prev_rx, prev_ry, params):
    """Convert one tick of mouse movement into smoothed right-stick values."""
    # When mouse is not moving, immediately decay/snap stick to neutral with ZERO upward drift
    if abs(dx) == 0 and abs(dy) == 0:
        return 0.0, 0.0

    input_x = float(dx)
    input_y = float(dy) if params["invert_y"] else float(-dy)
    mag = math.hypot(input_x, input_y)

    if mag == 0.0:
        return 0.0, 0.0

    nx, ny = input_x / mag, input_y / mag
    powered = math.pow(mag * params["sensitivity"], params["exponent"])
    ad = params["anti_deadzone"]
    out = min(1.0, max(0.0, ad + (1.0 - ad) * powered))

    sm = params["smoothing"]
    rx = prev_rx * sm + nx * out * (1.0 - sm)
    ry = prev_ry * sm + ny * out * (1.0 - sm)

    length = math.hypot(rx, ry)
    if length > 1.0:
        rx, ry = rx / length, ry / length
    return rx, ry


# ==============================================================================
# ENGINE
# ==============================================================================
class Engine:
    """Owns the virtual controller, the input hooks, and the aim thread."""

    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self.params = dict(DEFAULT_CONFIG)
        self.load_config()

        self.active = False
        self.running = False
        self.shutdown_requested = threading.Event()
        self.auto_test_running = False

        self._lock = threading.RLock()        # guards gamepad + controller state
        self._delta_lock = threading.Lock()   # guards accumulated mouse movement
        self._toggle_lock = threading.Lock()  # serialises F8 toggles

        self._held = set()          # logical keys currently held (while active)
        self._buttons = set()       # controller buttons currently pressed
        self._passthrough = set()   # keys already down when we activated
        self._f8_down = False
        self._first_aim_tick = True
        self._anchor = (0, 0)
        self._acc_dx = 0
        self._acc_dy = 0

        self.lx = self.ly = self.rx = self.ry = 0.0
        self.lt = self.rt = 0.0
        self.mouse_events = 0
        self.last_delta = (0, 0)

        self._kb_listener = None
        self._mouse_listener = None
        self._aim_thread = None

        self.gamepad = vg.VX360Gamepad()
        self.gamepad.reset()
        self.gamepad.update()

    # ---------------------------------------------------------------- config
    def load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            print(f"Warning: could not read config.json ({exc}). Using defaults.")
            return
        if not isinstance(saved, dict):
            return
        for key, default in DEFAULT_CONFIG.items():
            if key not in saved:
                continue
            try:
                if isinstance(default, bool):
                    self.params[key] = bool(saved[key])
                else:
                    lo, hi = LIMITS[key]
                    self.params[key] = min(hi, max(lo, float(saved[key])))
            except (TypeError, ValueError):
                pass

    def save_config(self):
        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.config_path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.params, f, indent=4)
            os.replace(tmp, self.config_path)
            print(f"Saved settings to {self.config_path}")
            return True
        except OSError as exc:
            print(f"Error saving config.json: {exc}")
            return False

    # ------------------------------------------------------------- lifecycle
    def start(self):
        if self.running:
            return
        self.running = True
        self._kb_listener = keyboard.Listener(win32_event_filter=self._kb_filter)
        self._mouse_listener = mouse.Listener(win32_event_filter=self._mouse_filter)
        self._aim_thread = threading.Thread(target=self._aim_loop, name="aim", daemon=True)
        self._aim_thread.start()
        self._kb_listener.start()
        self._mouse_listener.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.set_active(False)
        for listener in (self._kb_listener, self._mouse_listener):
            try:
                if listener:
                    listener.stop()
            except Exception:
                pass
        if self._aim_thread:
            self._aim_thread.join(timeout=1.0)
        self.reset_inputs()

    def request_shutdown(self):
        self.set_active(False)
        self.shutdown_requested.set()

    # ----------------------------------------------------------- active mode
    def toggle(self):
        self.set_active(not self.active)

    def set_active(self, on):
        on = bool(on)
        with self._toggle_lock:
            if on == self.active:
                return
            if on:
                self.reset_inputs()
                self._seed_passthrough()
                self._first_aim_tick = True
                self.active = True
                self._wakeup_pulse()
                print(">>> ACTIVE: keyboard/mouse now drive the virtual Xbox controller <<<")
            else:
                self.active = False
                self._passthrough.clear()
                self.reset_inputs()
                print(">>> PAUSED: normal keyboard/mouse restored <<<")

    def set_aim_only(self, value):
        self.params["aim_only"] = bool(value)
        with self._lock:
            self._held.clear()
            if self.active:
                self._sync_keyboard_locked()

    def reset_inputs(self):
        with self._delta_lock:
            self._acc_dx = self._acc_dy = 0
        with self._lock:
            self._held.clear()
            self._buttons.clear()
            self.lx = self.ly = self.rx = self.ry = 0.0
            self.lt = self.rt = 0.0
            self.gamepad.reset()
            self.gamepad.update()

    def snapshot(self):
        with self._lock:
            return {
                "active": self.active,
                "lx": self.lx, "ly": self.ly, "rx": self.rx, "ry": self.ry,
                "lt": self.lt, "rt": self.rt,
                "buttons": sorted(self._buttons),
                "mouse_events": self.mouse_events,
                "last_delta": self.last_delta,
            }

    # --------------------------------------------------------------- helpers
    def _seed_passthrough(self):
        self._passthrough.clear()
        for vk in VK_TO_KEY:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                self._passthrough.add(vk)

    def _wakeup_pulse(self):
        """Stick deflection past Roblox deadzone so Roblox switches UI to Xbox-controller icons."""
        def pulse():
            time.sleep(0.04)
            with self._lock:
                if not self.active:
                    return
                self.gamepad.left_joystick_float(0.0, 0.40)
                self.gamepad.update()
            time.sleep(0.08)
            with self._lock:
                if self.active and not self._held:
                    self.gamepad.left_joystick_float(0.0, 0.0)
                    self.gamepad.update()
        threading.Thread(target=pulse, name="wakeup", daemon=True).start()

    def run_auto_test(self, on_tick=None, on_done=None):
        """Runs a 4-second automated movement and button test to prove Roblox receives inputs."""
        if self.auto_test_running:
            return
        self.auto_test_running = True

        def _test():
            t_start = time.time()
            step = 0
            while self.running and (time.time() - t_start < 4.0):
                with self._lock:
                    self.lx, self.ly = 0.0, 1.0
                    self.rx, self.ry = 0.6, 0.0
                    self.gamepad.left_joystick_float(0.0, 1.0)
                    self.gamepad.right_joystick_float(0.6, 0.0)

                    if step % 2 == 0:
                        self.gamepad.release_button(BUTTON_MAP["L3"])
                        self.gamepad.press_button(BUTTON_MAP["A"])
                    else:
                        self.gamepad.release_button(BUTTON_MAP["A"])
                        self.gamepad.press_button(BUTTON_MAP["L3"])
                    self.gamepad.update()

                step += 1
                time.sleep(0.4)

            with self._lock:
                self.reset_inputs()
            self.auto_test_running = False
            if on_done:
                on_done()

        threading.Thread(target=_test, name="auto_test", daemon=True).start()

    def _sync_keyboard_locked(self):
        held = self._held
        y = (1.0 if "w" in held else 0.0) - (1.0 if "s" in held else 0.0)
        x = (1.0 if "d" in held else 0.0) - (1.0 if "a" in held else 0.0)
        if x and y:
            x, y = x * DIAGONAL, y * DIAGONAL
        self.lx, self.ly = x, y

        desired = {btn for btn, keys in BUTTON_BINDINGS.items() if keys & held}
        for btn in desired - self._buttons:
            self.gamepad.press_button(button=BUTTON_MAP[btn])
        for btn in self._buttons - desired:
            self.gamepad.release_button(button=BUTTON_MAP[btn])
        self._buttons = set(desired)

        self.gamepad.left_joystick_float(x_value_float=x, y_value_float=y)
        self.gamepad.update()

    # ------------------------------------------------------------ input hooks
    def _kb_filter(self, msg, data):
        try:
            suppress = self._handle_key(msg, data)
        except Exception:
            traceback.print_exc()
            suppress = False
        if suppress:
            self._kb_listener.suppress_event()
        return True

    def _mouse_filter(self, msg, data):
        try:
            suppress = self._handle_mouse(msg, data)
        except Exception:
            traceback.print_exc()
            suppress = False
        if suppress:
            self._mouse_listener.suppress_event()
        return True

    def _handle_key(self, msg, data):
        vk = data.vkCode
        is_down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = msg in (WM_KEYUP, WM_SYSKEYUP)

        if vk == VK_END:                      # kill-switch, never suppressed
            if is_down:
                self.request_shutdown()
            return False

        if vk == VK_F8:                       # toggle, never suppressed
            if is_down:
                if not self._f8_down:         # ignore key-repeat while held
                    self._f8_down = True
                    self.toggle()
            elif is_up:
                self._f8_down = False
            return False

        if not self.active or self.params["aim_only"]:
            return False

        if vk in self._passthrough:
            if is_up:
                self._passthrough.discard(vk)
            return False

        key = VK_TO_KEY.get(vk)
        if key is None:
            return False                      # Esc, Enter, Tab, chat... pass through

        with self._lock:
            # Key-Repeat Debounce: only re-sync if held state actually changed
            if is_down:
                if key in self._held:
                    return True  # already registered down, suppress repeat event
                self._held.add(key)
            elif is_up:
                if key not in self._held:
                    return True
                self._held.discard(key)
            self._sync_keyboard_locked()
        return True

    def _handle_mouse(self, msg, data):
        if not self.active:
            return False
        if data.flags & LLMHF_INJECTED:
            return False

        if msg in (WM_LBUTTONDOWN, WM_LBUTTONUP):          # shoot -> RT
            with self._lock:
                self.rt = 1.0 if msg == WM_LBUTTONDOWN else 0.0
                self.gamepad.right_trigger_float(value_float=self.rt)
                self.gamepad.update()
            return True

        if msg in (WM_RBUTTONDOWN, WM_RBUTTONUP):          # aim -> LT
            with self._lock:
                self.lt = 1.0 if msg == WM_RBUTTONDOWN else 0.0
                self.gamepad.left_trigger_float(value_float=self.lt)
                self.gamepad.update()
            return True

        if msg == WM_MOUSEMOVE:                            # look -> right stick
            cur = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(cur)):
                return self.params.get("block_mouse_move", True)

            dx = data.pt.x - cur.x
            dy = data.pt.y - cur.y

            if dx != 0 or dy != 0:
                with self._delta_lock:
                    self._acc_dx += dx
                    self._acc_dy += dy
                self.mouse_events += 1
                self.last_delta = (dx, dy)

            # Suppress physical cursor move so OS cursor stays naturally frozen
            return self.params.get("block_mouse_move", True)

        return False

    # --------------------------------------------------------------- aim loop
    def _aim_loop(self):
        interval = 1.0 / UPDATE_RATE_HZ
        winmm.timeBeginPeriod(1)
        try:
            while self.running:
                if not self.active:
                    time.sleep(0.016)
                    continue

                with self._delta_lock:
                    dx, dy = self._acc_dx, self._acc_dy
                    self._acc_dx = self._acc_dy = 0

                new_rx, new_ry = compute_right_stick(dx, dy, self.rx, self.ry, self.params)
                if round(new_rx, 3) != round(self.rx, 3) or round(new_ry, 3) != round(self.ry, 3):
                    with self._lock:
                        if self.active:
                            self.rx, self.ry = new_rx, new_ry
                            self.gamepad.right_joystick_float(x_value_float=new_rx, y_value_float=new_ry)
                            self.gamepad.update()
                time.sleep(interval)
        except Exception:
            traceback.print_exc()
        finally:
            winmm.timeEndPeriod(1)
