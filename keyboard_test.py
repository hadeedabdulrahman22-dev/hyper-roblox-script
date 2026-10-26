import sys
import time
import vgamepad as vg
from pynput import keyboard

# Force unbuffered output so print statements show immediately
sys.stdout.reconfigure(line_buffering=True)

# Global State
is_active = False
held_keys = set()
curr_stick_x = 0.0
curr_stick_y = 0.0
pressed_buttons = set()

# Initialize Gamepad
try:
    gamepad = vg.VX360Gamepad()
    gamepad.reset()
    gamepad.update()
except Exception as e:
    print(f"ERROR: Could not initialize virtual controller: {e}", flush=True)
    sys.exit(1)

# Button Mappings
BUTTON_MAP = {
    'A': vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    'B': vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    'X': vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    'Y': vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    'RB': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    'LB': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
}

def normalize_key(key):
    """Normalize pynput key to a clean lowercase string."""
    if hasattr(key, 'char') and key.char is not None:
        return key.char.lower()
    if hasattr(key, 'name') and key.name is not None:
        return key.name.lower()
    return str(key).lower()

def update_controller():
    global curr_stick_x, curr_stick_y

    if not is_active:
        return

    # 1. Compute WASD Left Joystick
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

    # Diagonal normalization
    if target_x != 0.0 and target_y != 0.0:
        target_x /= 1.414
        target_y /= 1.414

    stick_changed = False
    if round(target_x, 3) != round(curr_stick_x, 3) or round(target_y, 3) != round(curr_stick_y, 3):
        curr_stick_x = target_x
        curr_stick_y = target_y
        gamepad.left_joystick_float(x_value_float=curr_stick_x, y_value_float=curr_stick_y)
        stick_changed = True

    # 2. Compute Button States
    desired_buttons = set()
    if 'space' in held_keys:
        desired_buttons.add('A')
    if 'c' in held_keys or 'shift' in held_keys or 'shift_l' in held_keys:
        desired_buttons.add('B')
    if 'r' in held_keys:
        desired_buttons.add('X')
    if 'q' in held_keys:
        desired_buttons.add('Y')
    if 'e' in held_keys:
        desired_buttons.add('RB')
    if 'f' in held_keys:
        desired_buttons.add('LB')

    button_changes = []
    # Buttons to press
    for btn in desired_buttons - pressed_buttons:
        gamepad.press_button(button=BUTTON_MAP[btn])
        pressed_buttons.add(btn)
        button_changes.append(f"{btn} Pressed")

    # Buttons to release
    for btn in pressed_buttons - desired_buttons:
        gamepad.release_button(button=BUTTON_MAP[btn])
        button_changes.append(f"{btn} Released")
    for btn in list(pressed_buttons - desired_buttons):
        pressed_buttons.remove(btn)

    # 3. Apply changes and print live feedback
    if stick_changed or button_changes:
        gamepad.update()
        event_str = " | ".join(button_changes) if button_changes else "Direction Updated"
        print(f"[ACTIVE] Stick: ({curr_stick_x:.2f}, {curr_stick_y:.2f}) | {event_str}", flush=True)

def reset_all_inputs():
    global curr_stick_x, curr_stick_y, pressed_buttons, held_keys
    held_keys.clear()
    pressed_buttons.clear()
    curr_stick_x = 0.0
    curr_stick_y = 0.0
    gamepad.reset()
    gamepad.update()

def on_press(key):
    global is_active
    k = normalize_key(key)

    # Kill switch: END
    if k == 'end':
        print("\n" + "="*55, flush=True)
        print("[KILL-SWITCH] 'END' pressed! Resetting controller and exiting...", flush=True)
        print("="*55, flush=True)
        reset_all_inputs()
        return False  # Stop listener

    # Toggle active: F8
    if k == 'f8':
        is_active = not is_active
        reset_all_inputs()
        if is_active:
            print("\n>>> STATUS: [ACTIVE] - Keyboard is now controlling the virtual gamepad! <<<", flush=True)
            print("    (Press F8 to pause, or END to exit)\n", flush=True)
        else:
            print("\n>>> STATUS: [PAUSED] - Virtual gamepad reset to neutral. <<<", flush=True)
            print("    (Press F8 to resume, or END to exit)\n", flush=True)
        return

    # Ignore inputs if paused
    if not is_active:
        return

    # Ignore OS key repeat events
    if k in held_keys:
        return

    held_keys.add(k)
    update_controller()

def on_release(key):
    k = normalize_key(key)

    if k in held_keys:
        held_keys.remove(k)
        if is_active:
            update_controller()

def main():
    print("="*60, flush=True)
    print("  KBM-to-XInput Virtual Controller: Phase 2 (Movement & Buttons)", flush=True)
    print("="*60, flush=True)
    print("Global Controls:", flush=True)
    print("  [F8]       : Toggle ACTIVE / PAUSED (Default: PAUSED)", flush=True)
    print("  [END]      : Kill-Switch (Instantly resets controller and exits)", flush=True)
    print(flush=True)
    print("Keyboard -> Virtual Controller Mappings:", flush=True)
    print("  W / A / S / D  -> Left Analog Stick (Normalized diagonals)", flush=True)
    print("  Space          -> [A] (Jump)", flush=True)
    print("  Left Shift / C -> [B] (Slide / Crouch)", flush=True)
    print("  R              -> [X] (Reload)", flush=True)
    print("  Q              -> [Y] (Swap Weapon)", flush=True)
    print("  E              -> [RB] (Ability)", flush=True)
    print("  F              -> [LB] (Ability)", flush=True)
    print("="*60, flush=True)
    print(">>> STATUS: [PAUSED] - Press F8 to begin controlling <<<", flush=True)
    print("="*60 + "\n", flush=True)

    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
    finally:
        reset_all_inputs()
        print("Cleanup complete. Controller safely in neutral.", flush=True)

if __name__ == "__main__":
    main()
