"""Unit test suite for Phase 11: Aim Assist Fixes, Exponential Decay (0.78), Aim Assist Lock (0.26 / 0.22), and Key Suppression."""
import math
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from controller_core import (
    DEFAULT_CONFIG,
    WM_KEYDOWN,
    WM_KEYUP,
    VK_END,
    VK_F8,
    Engine,
    compute_right_stick,
)
from app import ControllerApp


class MockData:
    def __init__(self, vk):
        self.vkCode = vk


def test_exponential_decay_unengaged():
    """Verify right stick decays with factor 0.78 per tick and cleanly snaps to 0.0 once < 0.02."""
    params = dict(DEFAULT_CONFIG)
    rx, ry = 0.5, 0.0
    
    # Tick 1
    new_rx, new_ry = compute_right_stick(0, 0, rx, ry, params, is_engaged=False)
    assert abs(new_rx - (0.5 * 0.78)) < 1e-4, f"Expected {0.5 * 0.78}, got {new_rx}"
    assert new_ry == 0.0

    # Simulate subsequent idle ticks
    curr_rx, curr_ry = new_rx, new_ry
    ticks = 1
    snapped = False
    for _ in range(25):
        curr_rx, curr_ry = compute_right_stick(0, 0, curr_rx, curr_ry, params, is_engaged=False)
        ticks += 1
        if curr_rx == 0.0 and curr_ry == 0.0:
            snapped = True
            break

    assert snapped, "Right stick must snap to 0.0 after decay"
    assert ticks <= 18, f"Decay must finish in ~60-90ms (< 18 ticks at 120Hz), took {ticks}"
    print("[PASS] test_exponential_decay_unengaged passed.")


def test_aim_assist_lock_micro_hold():
    """Verify right stick holds at max(anti_deadzone, 0.12) = 0.22 in last aim direction when is_engaged=True."""
    params = dict(DEFAULT_CONFIG)
    rx, ry = 0.5, 0.0
    last_dir = (1.0, 0.0)

    # Decay down while engaged
    curr_rx, curr_ry = rx, ry
    for _ in range(25):
        curr_rx, curr_ry = compute_right_stick(0, 0, curr_rx, curr_ry, params, is_engaged=True, last_dir=last_dir)

    expected_min = max(params.get("anti_deadzone", 0.22), 0.12)
    mag = math.hypot(curr_rx, curr_ry)
    assert abs(mag - expected_min) < 1e-4, f"Engaged stick must hold at {expected_min} magnitude, got {mag}"
    assert abs(curr_rx - expected_min) < 1e-4
    assert abs(curr_ry - 0.0) < 1e-4

    # Test angled direction (e.g. 0.0, 1.0)
    last_dir = (0.0, 1.0)
    curr_rx, curr_ry = 0.0, 0.4
    for _ in range(25):
        curr_rx, curr_ry = compute_right_stick(0, 0, curr_rx, curr_ry, params, is_engaged=True, last_dir=last_dir)

    assert abs(curr_rx - 0.0) < 1e-4
    assert abs(curr_ry - expected_min) < 1e-4
    print("[PASS] test_aim_assist_lock_micro_hold passed.")


def test_aim_assist_lock_micro_strafe():
    """Verify Left Stick micro-strafe oscillates ±0.26 (above Hypershot 0.25 deadzone) every 140ms when standing still and aiming/shooting."""
    engine = Engine()
    engine.params["aim_assist_lock"] = True
    engine.lt = 1.0  # Aiming down sights (RMB)
    engine._held_vks.clear()

    engine._sync_keyboard_locked()
    assert abs(engine.lx) == 0.26, f"Expected micro-strafe 0.26, got {engine.lx}"
    assert engine.ly == 0.0

    # When user actively presses 'A' (VK 0x41), player movement takes priority
    engine._held_vks.add(0x41)  # 'A' = move_left
    engine._sync_keyboard_locked()
    assert engine.lx == -1.0, f"Player movement must override booster strafe, got {engine.lx}"

    engine._held_vks.clear()
    engine.lt = 0.0
    engine.rt = 0.0
    engine._sync_keyboard_locked()
    assert engine.lx == 0.0, f"When neither LT nor RT is pressed, idle stick must be 0.0, got {engine.lx}"
    print("[PASS] test_aim_assist_lock_micro_strafe passed.")


def test_unmapped_keys_suppression():
    """Verify unmapped keys are suppressed while ACTIVE, but F8 and END are always passed through."""
    engine = Engine()
    engine.active = True
    engine.params["aim_only"] = False

    # VK_Z (0x5A) is unmapped in default config
    unmapped_data = MockData(0x5A)
    assert engine._handle_key(WM_KEYDOWN, unmapped_data) is True, "Unmapped key must be suppressed while ACTIVE"

    # VK_F8 and VK_END must NEVER be suppressed
    f8_data = MockData(VK_F8)
    assert engine._handle_key(WM_KEYDOWN, f8_data) is False, "F8 must NEVER be suppressed"
    assert engine._handle_key(WM_KEYUP, f8_data) is False, "F8 up must NEVER be suppressed"

    end_data = MockData(VK_END)
    assert engine._handle_key(WM_KEYDOWN, end_data) is False, "END must NEVER be suppressed"

    # When paused (active=False), keys are not suppressed
    engine.active = False
    assert engine._handle_key(WM_KEYDOWN, unmapped_data) is False, "Keys must not be suppressed when PAUSED"
    print("[PASS] test_unmapped_keys_suppression passed.")


def test_app_gui_aim_lock_integration():
    """Verify GUI contains Aim Assist Lock checkbox and toggling updates engine params."""
    engine = Engine()
    app = ControllerApp(engine)

    assert hasattr(app, "aim_lock_var"), "app must have aim_lock_var"
    assert app.aim_lock_var.get() is True, "aim_lock_var should default to True"

    app.aim_lock_var.set(False)
    app.on_aim_lock_toggle()
    assert engine.params["aim_assist_lock"] is False, "Engine param must update to False"

    app.aim_lock_var.set(True)
    app.on_aim_lock_toggle()
    assert engine.params["aim_assist_lock"] is True, "Engine param must update to True"

    app.on_closing()
    print("[PASS] test_app_gui_aim_lock_integration passed.")


if __name__ == "__main__":
    test_exponential_decay_unengaged()
    test_aim_assist_lock_micro_hold()
    test_aim_assist_lock_micro_strafe()
    test_unmapped_keys_suppression()
    test_app_gui_aim_lock_integration()
    print("\nALL PHASE 11 AIM ASSIST TESTS PASSED!")
