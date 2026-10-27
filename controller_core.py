import ctypes
from ctypes import wintypes
import math
import sys
import threading
import time
import vgamepad as vg
from pynput import keyboard, mouse

# Force immediate unbuffered console output
sys.stdout.reconfigure(line_buffering=True)

# ==============================================================================
# CONFIGURATION & PARAMETERS (PHASE 7)
# ==============================================================================
SENSITIVITY = 0.055          # High responsiveness for controller thumbstick look
ANTI_DEADZONE = 0.18        # Breaks game deadzone immediately on micro-movements
EXPONENT = 0.85             # Sub-linear response curve for fine micro-aim + fast snap flicks
SMOOTHING = 0.40            # Anti-jitter filtering
INVERT_Y = False            # Normal (mouse-up = stick-up)
AIM_ONLY = False            # False = Full Controller Mode (suppresses physical KBM)
BLOCK_MOUSE_MOVE = False    # False = Unchecked (normal GetCursorPos / SetCursorPos loop)
UPDATE_RATE_HZ = 120        # 120Hz precision polling loop

# ==============================================================================
# WINDOWS API & STRUCTURES
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
first_aim_tick = True

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
    0x10: 'shift',      # Shift (Slide)
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
# XINPUT SLOT DETECTION
# ==============================================================================
def get_connected_xinput_slot():
    """Returns the XInput slot number (0-3) if connected, or None."""
    class XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [
            ('wButtons', wintypes.WORD),
            ('bLeftTrigger', wintypes.BYTE),
            ('bRightTrigger', wintypes.BYTE),
            ('sThumbLX', wintypes.SHORT),
            ('sThumbLY', wintypes.SHORT),
            ('sThumbRX', wintypes.SHORT),
            ('sThumbRY', wintypes.SHORT),
        ]
    class XINPUT_STATE(ctypes.Structure):
        _fields_ = [
            ('dwPacketNumber', wintypes.DWORD),
            ('Gamepad', XINPUT_GAMEPAD),
        ]

    for dll in ['xinput1_4.dll', 'xinput1_3.dll', 'xinput9_1_0.dll']:
        try:
            xi = ctypes.windll.LoadLibrary(dll)
            state = XINPUT_STATE()
            for slot in range(4):
                if xi.XInputGetState(slot, ctypes.byref(state)) == 0:
                    return slot
        except Exception:
            continue
    return None

# ==============================================================================
# CONTROLLER RESET & WAKE-UP
# ==============================================================================
def reset_all_inputs():
    """Resets all virtual sticks, triggers, buttons to neutral."""
    global curr_lx, curr_ly, curr_rx, curr_ry, curr_lt, curr_rt, held_keys, pressed_buttons
    global accum_mouse_dx, accum_mouse_dy
    with mouse_delta_lock:
        accum_mouse_dx = 0
        accum_mouse_dy = 0

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
    """Sends a virtual gamepad wake-up pulse so Roblox switches HUD to Xbox controller badges."""
    def _pulse():
        time.sleep(0.04)
        with gamepad_lock:
            # Send stick deflection past deadzone to trigger Gamepad1 recognition in Roblox
            gamepad.left_joystick_float(0.0, 0.40)
            gamepad.update()
        time.sleep(0.08)
        with gamepad_lock:
            gamepad.left_joystick_float(0.0, 0.0)
            gamepad.update()
    threading.Thread(target=_pulse, daemon=True).start()

# ==============================================================================
# KEYBOARD INPUT HANDLERS (WASD & HUD ACTIONS)
# ==============================================================================
def update_keyboard_controller():
    global curr_lx, curr_ly

    if not is_active or AIM_ONLY:
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
    """Processes key-down and key-up BEFORE suppression; debounces key repeats."""
    global is_active, running
    vk = data.vkCode

    # 1. Kill-Switch: END (Never suppressed - safety exit)
    if vk == VK_END:
        if msg in (0x0100, 0x0104):
            print("\n[KILL-SWITCH] 'END' pressed! Stopping controller...", flush=True)
            running = False
            is_active = False
            reset_all_inputs()
        return True

    # 2. Toggle Active/Paused: F8 (Never suppressed)
    if vk == VK_F8:
        if msg in (0x0100, 0x0104):
            is_active = not is_active
            reset_all_inputs()
            if is_active:
                send_controller_wakeup_pulse()
                print("\n>>> STATUS: [ACTIVE] - Physical inputs suppressed, Virtual Xbox engaged! <<<", flush=True)
            else:
                print("\n>>> STATUS: [PAUSED] - Normal Keyboard/Mouse restored. <<<", flush=True)
        return True

    # If PAUSED or Aim-Only, allow normal physical keys
    if not is_active or AIM_ONLY:
        return True

    # 3. Mapped HUD Keys: Update Virtual Controller State, then Suppress
    if vk in VK_MAPPINGS:
        key_name = VK_MAPPINGS[vk]
        is_press = (msg in (0x0100, 0x0104))
        is_release = (msg in (0x0101, 0x0105))

        # Key-Repeat Flood Fix: Only update if state actually changed!
        if is_press:
            if key_name not in held_keys:
                held_keys.add(key_name)
                update_keyboard_controller()
        elif is_release:
            if key_name in held_keys:
                held_keys.remove(key_name)
                update_keyboard_controller()

        # Suppress physical key from reaching the game window
        if kb_listener:
            kb_listener.suppress_event()

    return True

def mouse_event_filter(msg, data):
    """Processes mouse clicks & movement."""
    global curr_lt, curr_rt, accum_mouse_dx, accum_mouse_dy
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
        # If Block Physical Mouse Move is OFF, let 120Hz loop handle cursor via Get/SetCursorPos
        if not BLOCK_MOUSE_MOVE:
            return True

        if data.flags & 1:
            if mouse_listener:
                mouse_listener.suppress_event()
            return True

        # Use actual current OS cursor position as the anchor reference
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        dx = data.pt.x - pt.x
        dy = data.pt.y - pt.y

        if dx != 0 or dy != 0:
            with mouse_delta_lock:
                accum_mouse_dx += dx
                accum_mouse_dy += dy

        if mouse_listener:
            mouse_listener.suppress_event()

    return True

# ==============================================================================
# MOUSE AIM LOOP (120Hz HIGH-PRECISION THREAD)
# ==============================================================================
def calculate_right_stick(dx, dy, prev_rx, prev_ry):
    input_x = float(dx)
    input_y = float(dy) if INVERT_Y else float(-dy)
    mag = math.hypot(input_x, input_y)

    if mag == 0.0:
        decay_rx = prev_rx * 0.2
        decay_ry = prev_ry * 0.2
        if abs(decay_rx) < 0.02 and abs(decay_ry) < 0.02:
            return 0.0, 0.0
        return decay_rx, decay_ry

    nx = input_x / mag
    ny = input_y / mag

    scaled = mag * SENSITIVITY
    powered = math.pow(scaled, EXPONENT)

    output_mag = ANTI_DEADZONE + (1.0 - ANTI_DEADZONE) * powered
    output_mag = min(1.0, max(0.0, output_mag))

    raw_rx = nx * output_mag
    raw_ry = ny * output_mag

    smoothed_rx = prev_rx * SMOOTHING + raw_rx * (1.0 - SMOOTHING)
    smoothed_ry = prev_ry * SMOOTHING + raw_ry * (1.0 - SMOOTHING)

    final_mag = math.hypot(smoothed_rx, smoothed_ry)
    if final_mag > 1.0:
        smoothed_rx /= final_mag
        smoothed_ry /= final_mag

    return smoothed_rx, smoothed_ry

def mouse_aim_worker():
    global curr_rx, curr_ry, first_aim_tick
    pt = POINT()
    tick_interval = 1.0 / UPDATE_RATE_HZ
    winmm.timeBeginPeriod(1)

    try:
        while running:
            if not is_active:
                time.sleep(0.016)
                continue

            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            center_x = screen_w // 2
            center_y = screen_h // 2

            if not BLOCK_MOUSE_MOVE:
                user32.GetCursorPos(ctypes.byref(pt))

                if first_aim_tick:
                    user32.SetCursorPos(center_x, center_y)
                    first_aim_tick = False
                    curr_rx = 0.0
                    curr_ry = 0.0
                    time.sleep(tick_interval)
                    continue

                dx = pt.x - center_x
                dy = pt.y - center_y
                user32.SetCursorPos(center_x, center_y)
            else:
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
# MAIN ENTRY POINT
# ==============================================================================
def main():
    global kb_listener, mouse_listener
    print("="*65, flush=True)
    print("  KBM-to-XInput Virtual Controller: Phase 7 Core", flush=True)
    print("="*65, flush=True)
    slot = get_connected_xinput_slot()
    if slot == 0:
        print("XInput Status: [CONNECTED ON SLOT 0 - Player 1] (Active for Roblox!)", flush=True)
    elif slot is not None:
        print(f"XInput Status: [CONNECTED ON SLOT {slot}] (Warning: Roblox prefers Slot 0)", flush=True)
    else:
        print("XInput Status: [NOT CONNECTED]", flush=True)

    print("Controls:")
    print("  [F8]   : Toggle Active / Paused (Suppresses physical inputs)")
    print("  [END]  : Emergency Kill-Switch & Exit")
    print(f"Aim Parameters: Sens={SENSITIVITY} | Anti-Deadzone={ANTI_DEADZONE} | Expo={EXPONENT}")
    print("="*65)
    print(">>> STATUS: [PAUSED] - Press F8 to begin controlling <<<")
    print("="*65 + "\n", flush=True)

    aim_thread = threading.Thread(target=mouse_aim_worker, daemon=True)
    aim_thread.start()

    kb_listener = keyboard.Listener(win32_event_filter=kb_event_filter)
    kb_listener.start()

    mouse_listener = mouse.Listener(win32_event_filter=mouse_event_filter)
    mouse_listener.start()

    try:
        while running:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        reset_all_inputs()
        kb_listener.stop()
        mouse_listener.stop()
        print("Shutdown complete. Controller in neutral, all inputs normal.", flush=True)

if __name__ == "__main__":
    main()
