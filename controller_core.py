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
    "anti_deadzone": 0.22,      # jump past the game's stick deadzone instantly (Hypershot deadzone: 0.25)
    "exponent": 0.85,           # <1 = more reactive to small movements
    "smoothing": 0.40,          # anti-jitter (0 = raw, higher = smoother)
    "invert_y": False,
    "aim_only": False,          # True = only mouse -> right stick, keyboard untouched
    "block_mouse_move": True,   # True = freeze physical cursor via hook suppression
    "always_on_top": True,
    "aim_assist_lock": True,    # True = keep stick above deadzone on LT/RT (Aim Assist Lock)
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

# ==============================================================================
# XBOX ACTIONS & DEFAULT KEYBINDS (PHASE 9)
# ==============================================================================
ACTIONS = [
    # 🕹️ Movement (Left Stick)
    {"id": "move_forward",  "name": "Move Forward",           "category": "Movement", "xbox": "LS Up",        "type": "stick",  "axis": "ly+", "default": ["W"]},
    {"id": "move_backward", "name": "Move Backward",          "category": "Movement", "xbox": "LS Down",      "type": "stick",  "axis": "ly-", "default": ["S"]},
    {"id": "move_left",     "name": "Move Left",              "category": "Movement", "xbox": "LS Left",      "type": "stick",  "axis": "lx-", "default": ["A"]},
    {"id": "move_right",    "name": "Move Right",             "category": "Movement", "xbox": "LS Right",     "type": "stick",  "axis": "lx+", "default": ["D"]},

    # ⚔️ Combat & Abilities
    {"id": "jump",          "name": "Jump",                   "category": "Combat",   "xbox": "A Button",     "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,              "default": ["SPACE"]},
    {"id": "slide",         "name": "Slide / Crouch",         "category": "Combat",   "xbox": "L3 (Left Stick Click)", "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB, "default": ["C", "LSHIFT"]},
    {"id": "ability_1",     "name": "Ability 1",              "category": "Combat",   "xbox": "LB (L1)",      "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER, "default": ["Q"]},
    {"id": "ability_2",     "name": "Ability 2",              "category": "Combat",   "xbox": "RB (R1)",      "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,"default": ["E"]},
    {"id": "ability_3",     "name": "Ability 3 / Ultimate",   "category": "Combat",   "xbox": "B Button",     "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,              "default": ["X"]},
    {"id": "reload",        "name": "Reload / Inspect",       "category": "Combat",   "xbox": "X Button",     "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,              "default": ["R", "V"]},
    {"id": "swap_weapons",  "name": "Swap Weapons",           "category": "Combat",   "xbox": "Y Button",     "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,              "default": ["1", "2"]},
    {"id": "equip_melee",   "name": "Equip Melee (Knife)",    "category": "Combat",   "xbox": "D-Pad Up",     "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,        "default": ["3"]},
    {"id": "quick_melee",   "name": "Quick Melee",            "category": "Combat",   "xbox": "R3 (Right Stick Click)", "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB, "default": ["F"]},
    {"id": "interact",      "name": "Interact / Use",         "category": "Combat",   "xbox": "X Button",     "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,              "default": ["G"]},

    # 📋 Menus & Navigation
    {"id": "emote",         "name": "Emote Wheel",            "category": "Menus",    "xbox": "D-Pad Left",   "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,      "default": ["B"]},
    {"id": "scoreboard",    "name": "Scoreboard",             "category": "Menus",    "xbox": "D-Pad Right",  "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,     "default": ["TAB"]},
    {"id": "dpad_down",     "name": "D-Pad Down",             "category": "Menus",    "xbox": "D-Pad Down",   "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,      "default": ["H"]},
    {"id": "menu_start",    "name": "In-Game Settings",       "category": "Menus",    "xbox": "Start / Menu", "type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,          "default": ["K"]},
    {"id": "cursor_back",   "name": "Roblox Virtual Cursor",  "category": "Menus",    "xbox": "Back / Select","type": "button", "btn": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,           "default": ["M"]},
]
ACTIONS_BY_ID = {a["id"]: a for a in ACTIONS}
DEFAULT_KEYBINDS = {a["id"]: list(a["default"]) for a in ACTIONS}

BUTTON_CODE_TO_NAME = {
    vg.XUSB_BUTTON.XUSB_GAMEPAD_A: "A",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_B: "B",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_X: "X",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_Y: "Y",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER: "LB",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER: "RB",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB: "L3",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB: "R3",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP: "DPAD_UP",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN: "DPAD_DOWN",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT: "DPAD_LEFT",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT: "DPAD_RIGHT",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_START: "START",
    vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK: "BACK",
}

# Backward compatibility maps
BUTTON_BINDINGS = {
    "A": {"space"},
    "B": {"x"},
    "X": {"r", "v"},
    "Y": {"1", "2"},
    "LB": {"q"},
    "RB": {"e"},
    "DPAD_UP": {"3"},
    "L3": {"c", "shift"},
    "R3": {"f"},
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
VK_TO_KEY = {
    ord("W"): "w", ord("A"): "a", ord("S"): "s", ord("D"): "d",
    0x20: "space", ord("C"): "c", 0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    ord("R"): "r", ord("V"): "v", ord("1"): "1", ord("2"): "2", ord("3"): "3",
    ord("Q"): "q", ord("E"): "e", ord("X"): "x", ord("F"): "f",
}

KEY_NAME_TO_VKS = {
    "SPACE": [0x20], "SPACEBAR": [0x20],
    "LSHIFT": [0xA0, 0x10], "RSHIFT": [0xA1, 0x10], "SHIFT": [0x10, 0xA0, 0xA1],
    "LCTRL": [0xA2, 0x11], "RCTRL": [0xA3, 0x11], "CTRL": [0x11, 0xA2, 0xA3],
    "LALT": [0xA4, 0x12], "RALT": [0xA5, 0x12], "ALT": [0x12, 0xA4, 0xA5],
    "TAB": [0x09],
    "CAPSLOCK": [0x14], "CAPS": [0x14],
    "ENTER": [0x0D], "RETURN": [0x0D],
    "BACKSPACE": [0x08],
    "ESCAPE": [0x1B], "ESC": [0x1B],
    "UP": [0x26], "DOWN": [0x28], "LEFT": [0x25], "RIGHT": [0x27],
    "INSERT": [0x2D], "DELETE": [0x2E], "HOME": [0x24], "END": [0x23],
    "PAGEUP": [0x21], "PAGEDOWN": [0x22],
    "`": [0xC0], "~": [0xC0], "TILDE": [0xC0],
    "-": [0xBD], "MINUS": [0xBD],
    "=": [0xBB], "EQUALS": [0xBB],
    "[": [0xDB], "]": [0xDD], "\\": [0xDC],
    ";": [0xBA], "'": [0xDE],
    ",": [0xBC], ".": [0xBE], "/": [0xBF],
}
for i in range(1, 13):
    KEY_NAME_TO_VKS[f"F{i}"] = [0x6F + i]
for i in range(10):
    KEY_NAME_TO_VKS[f"NUM{i}"] = [0x60 + i]


def name_to_vks(name):
    name = str(name).strip().upper()
    if name in KEY_NAME_TO_VKS:
        return KEY_NAME_TO_VKS[name]
    if len(name) == 1:
        if "A" <= name <= "Z":
            return [ord(name)]
        if "0" <= name <= "9":
            return [ord(name), 0x60 + int(name)]
    return []


def vk_to_name(vk):
    special = {
        0x20: "SPACE", 0xA0: "LSHIFT", 0xA1: "RSHIFT", 0x10: "SHIFT",
        0xA2: "LCTRL", 0xA3: "RCTRL", 0x11: "CTRL",
        0xA4: "LALT", 0xA5: "RALT", 0x12: "ALT",
        0x09: "TAB", 0x14: "CAPSLOCK", 0x0D: "ENTER", 0x08: "BACKSPACE",
        0x1B: "ESC", 0x26: "UP", 0x28: "DOWN", 0x25: "LEFT", 0x27: "RIGHT",
        0x2D: "INSERT", 0x2E: "DELETE", 0x24: "HOME", 0x23: "END",
        0x21: "PAGEUP", 0x22: "PAGEDOWN",
    }
    if vk in special:
        return special[vk]
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"NUM{vk - 0x60}"
    if 0x70 <= vk <= 0x7B:
        return f"F{vk - 0x6F}"
    scan = user32.MapVirtualKeyW(vk, 0)
    lparam = scan << 16
    buf = ctypes.create_unicode_buffer(32)
    user32.GetKeyNameTextW(lparam, buf, 32)
    val = buf.value.upper()
    return val if val else f"VK_{hex(vk)}"

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
def compute_right_stick(dx, dy, prev_rx, prev_ry, params, is_engaged=False, last_dir=(1.0, 0.0)):
    """Convert one tick of mouse movement into smoothed right-stick values.
    
    Uses a smooth exponential decay envelope (decay = 0.78 per 120Hz tick) when mouse
    stops moving so aim assist magnetism does not drop out between discrete mouse packets.
    """
    if abs(dx) == 0 and abs(dy) == 0:
        decay = 0.78
        rx = prev_rx * decay
        ry = prev_ry * decay

        # Aim Assist Lock (Deadzone Keeper): keep stick above deadzone in last aimed direction on LT/RT
        if is_engaged:
            min_mag = max(params.get("anti_deadzone", 0.22), 0.12)
            mag = math.hypot(rx, ry)
            if mag < min_mag:
                nx, ny = last_dir
                if nx == 0.0 and ny == 0.0:
                    nx = 1.0
                return nx * min_mag, ny * min_mag
            return rx, ry

        # When not actively aiming/shooting, snap strictly to (0.0, 0.0) once magnitude < 0.02
        if math.hypot(rx, ry) < 0.02:
            return 0.0, 0.0
        return rx, ry

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
        self.keybinds = {a["id"]: list(a["default"]) for a in ACTIONS}

        self.active = False
        self.running = False
        self.shutdown_requested = threading.Event()
        self.auto_test_running = False

        self._lock = threading.RLock()        # guards gamepad + controller state
        self._delta_lock = threading.Lock()   # guards accumulated mouse movement
        self._toggle_lock = threading.Lock()  # serialises F8 toggles

        self._held_vks = set()      # physical VK codes currently held down
        self._buttons = set()       # controller buttons currently pressed (XUSB button values)
        self._passthrough = set()   # keys already down when we activated
        self._f8_down = False
        self._first_aim_tick = True
        self._acc_dx = 0
        self._acc_dy = 0
        self._last_aim_dir = (1.0, 0.0)

        self._rebind_action = None
        self._rebind_on_done = None
        self._rebind_on_cancel = None

        self._vk_to_actions = {}
        self._all_mapped_vks = set()
        self._compile_keybinds()
        self.load_config()

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

    # ----------------------------------------------------------- keybinds & config
    def _compile_keybinds(self):
        """Compiles self.keybinds into fast VK lookup tables."""
        vk_to_actions = {}
        all_mapped_vks = set()

        for action_id, keys in self.keybinds.items():
            if action_id not in ACTIONS_BY_ID:
                continue
            for key_name in keys:
                vks = name_to_vks(key_name)
                for vk in vks:
                    all_mapped_vks.add(vk)
                    if vk not in vk_to_actions:
                        vk_to_actions[vk] = []
                    if action_id not in vk_to_actions[vk]:
                        vk_to_actions[vk].append(action_id)

        self._vk_to_actions = vk_to_actions
        self._all_mapped_vks = all_mapped_vks

    def start_rebind(self, action_id, on_done=None, on_cancel=None):
        with self._lock:
            self._rebind_action = action_id
            self._rebind_on_done = on_done
            self._rebind_on_cancel = on_cancel

    def cancel_rebind(self):
        cb = None
        action_id = None
        with self._lock:
            action_id = self._rebind_action
            cb = self._rebind_on_cancel
            self._rebind_action = None
            self._rebind_on_done = None
            self._rebind_on_cancel = None
        if cb and action_id:
            cb(action_id)

    def finish_rebind(self, vk):
        key_name = vk_to_name(vk)
        cb = None
        action_id = None
        with self._lock:
            action_id = self._rebind_action
            cb = self._rebind_on_done
            self._rebind_action = None
            self._rebind_on_done = None
            self._rebind_on_cancel = None

            if action_id:
                self.keybinds[action_id] = [key_name]
                self._compile_keybinds()
                self.save_config()

        if cb and action_id:
            cb(action_id, key_name)

    def update_keybind(self, action_id, keys):
        with self._lock:
            if action_id in ACTIONS_BY_ID:
                self.keybinds[action_id] = [str(k).upper() for k in keys]
                self._compile_keybinds()
                self.save_config()

    def reset_keybinds_to_default(self):
        with self._lock:
            self.keybinds = {a["id"]: list(a["default"]) for a in ACTIONS}
            self._compile_keybinds()
            self.save_config()

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

        if "rotational_booster" in saved and "aim_assist_lock" not in saved:
            self.params["aim_assist_lock"] = bool(saved["rotational_booster"])

        if "keybinds" in saved and isinstance(saved["keybinds"], dict):
            for aid in ACTIONS_BY_ID:
                if aid in saved["keybinds"] and isinstance(saved["keybinds"][aid], list):
                    self.keybinds[aid] = [str(k).upper() for k in saved["keybinds"][aid]]
                else:
                    self.keybinds[aid] = list(ACTIONS_BY_ID[aid]["default"])
            self._compile_keybinds()

    def save_config(self):
        try:
            data = dict(self.params)
            data["keybinds"] = dict(self.keybinds)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.config_path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
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
            self._held_vks.clear()
            if self.active:
                self._sync_keyboard_locked()

    def reset_inputs(self):
        with self._delta_lock:
            self._acc_dx = self._acc_dy = 0
        with self._lock:
            self._held_vks.clear()
            self._buttons.clear()
            self.lx = self.ly = self.rx = self.ry = 0.0
            self.lt = self.rt = 0.0
            self._last_aim_dir = (1.0, 0.0)
            self.gamepad.reset()
            self.gamepad.update()

    def snapshot(self):
        with self._lock:
            btn_names = sorted([BUTTON_CODE_TO_NAME.get(b, str(b)) for b in self._buttons])
            return {
                "active": self.active,
                "lx": self.lx, "ly": self.ly, "rx": self.rx, "ry": self.ry,
                "lt": self.lt, "rt": self.rt,
                "buttons": btn_names,
                "mouse_events": self.mouse_events,
                "last_delta": self.last_delta,
            }

    # --------------------------------------------------------------- helpers
    def _seed_passthrough(self):
        self._passthrough.clear()
        for vk in self._all_mapped_vks:
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
                if self.active and not self._held_vks:
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
                        self.gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB)
                        self.gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
                    else:
                        self.gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
                        self.gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB)
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
        active_actions = set()
        for vk in self._held_vks:
            for act in self._vk_to_actions.get(vk, []):
                active_actions.add(act)

        y = (1.0 if "move_forward" in active_actions else 0.0) - (1.0 if "move_backward" in active_actions else 0.0)
        x = (1.0 if "move_right" in active_actions else 0.0) - (1.0 if "move_left" in active_actions else 0.0)
        if x and y:
            x, y = x * DIAGONAL, y * DIAGONAL

        # Aim Assist Lock: apply micro-strafe if movement is idle and aiming/shooting
        lock_enabled = self.params.get("aim_assist_lock", self.params.get("rotational_booster", True))
        if lock_enabled and (self.lt > 0.1 or self.rt > 0.1):
            if x == 0.0 and y == 0.0:
                step = (int(time.time() * 1000) // 140) % 2
                x = 0.26 if step == 0 else -0.26

        self.lx, self.ly = x, y

        desired = set()
        for action_id in active_actions:
            act_info = ACTIONS_BY_ID.get(action_id)
            if act_info and act_info["type"] == "button":
                desired.add(act_info["btn"])

        for btn in desired - self._buttons:
            self.gamepad.press_button(button=btn)
        for btn in self._buttons - desired:
            self.gamepad.release_button(button=btn)
        self._buttons = desired

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

        # 1. Rebind capture mode
        if self._rebind_action is not None:
            if is_down:
                if vk == 0x1B:  # ESC -> cancel
                    self.cancel_rebind()
                    return True
                if vk in (VK_F8, VK_END):
                    return False  # Safety keys cannot be bound
                self.finish_rebind(vk)
                return True
            return True

        # 2. Safety keys: F8 (Toggle) & END (Kill-Switch)
        if vk == VK_END:
            if is_down:
                self.request_shutdown()
            return False

        if vk == VK_F8:
            if is_down:
                if not self._f8_down:
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

        if vk not in self._all_mapped_vks:
            # While ACTIVE in full controller mode, suppress ALL physical keys so Roblox NEVER
            # receives a stray keyboard input and switches away from Controller Mode
            return True

        with self._lock:
            # Key-Repeat Debounce: only re-sync if held state actually changed
            if is_down:
                if vk in self._held_vks:
                    return True
                self._held_vks.add(vk)
            elif is_up:
                if vk not in self._held_vks:
                    return True
                self._held_vks.discard(vk)

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

                lock_enabled = self.params.get("aim_assist_lock", self.params.get("rotational_booster", True))
                is_engaged = lock_enabled and (self.lt > 0.1 or self.rt > 0.1)

                if dx != 0 or dy != 0:
                    input_x = float(dx)
                    input_y = float(dy) if self.params["invert_y"] else float(-dy)
                    mag = math.hypot(input_x, input_y)
                    if mag > 0.0:
                        self._last_aim_dir = (input_x / mag, input_y / mag)

                new_rx, new_ry = compute_right_stick(
                    dx, dy, self.rx, self.ry, self.params,
                    is_engaged=is_engaged, last_dir=self._last_aim_dir
                )

                # Aim Assist Lock: Left Stick micro-strafe oscillation (±0.26 every 140ms, above 0.25 deadzone)
                has_move_keys = any(
                    act in ("move_forward", "move_backward", "move_left", "move_right")
                    for vk in self._held_vks
                    for act in self._vk_to_actions.get(vk, [])
                )
                if is_engaged and not has_move_keys:
                    step = (int(time.time() * 1000) // 140) % 2
                    target_lx = 0.26 if step == 0 else -0.26
                elif not has_move_keys:
                    target_lx = 0.0
                else:
                    target_lx = self.lx

                need_update = False
                with self._lock:
                    if self.active:
                        if round(new_rx, 3) != round(self.rx, 3) or round(new_ry, 3) != round(self.ry, 3):
                            self.rx, self.ry = new_rx, new_ry
                            self.gamepad.right_joystick_float(x_value_float=new_rx, y_value_float=new_ry)
                            need_update = True
                        if target_lx != self.lx:
                            self.lx = target_lx
                            self.gamepad.left_joystick_float(x_value_float=self.lx, y_value_float=self.ly)
                            need_update = True
                        if need_update:
                            self.gamepad.update()

                time.sleep(interval)
        except Exception:
            traceback.print_exc()
        finally:
            winmm.timeEndPeriod(1)
