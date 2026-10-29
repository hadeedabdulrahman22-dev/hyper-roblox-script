"""Unit test suite for Phase 12: Crisp 1:1 Right Stick Stopping, Subtle Left-Stick Strafe (0.07), and 0.05 Deadzone Tuning."""
import math
import os
import sys

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


def test_right_stick_crisp_stopping_dead():
    """Verify right stick has 1 grace tick at 0.5 decay, then snaps immediately to (0.0, 0.0) on tick 2."""
    params = dict(DEFAULT_CONFIG)
    rx, ry = 0.6, -0.4

    # Tick 1: 1 grace tick at 0.5 decay
    rx1, ry1 = compute_right_stick(0, 0, rx, ry, params, zero_ticks=1)
    assert abs(rx1 - 0.3) < 1e-4, f"Expected 0.3, got {rx1}"
    assert abs(ry1 - (-0.2)) < 1e-4, f"Expected -0.2, got {ry1}"

    # Tick 2: Immediate snap to (0.0, 0.0) (~16ms)
    rx2, ry2 = compute_right_stick(0, 0, rx1, ry1, params, zero_ticks=2)
    assert rx2 == 0.0 and ry2 == 0.0, f"Expected (0.0, 0.0) on tick 2, got ({rx2}, {ry2})"

    # Tick 3+: Remains strictly (0.0, 0.0)
    rx3, ry3 = compute_right_stick(0, 0, rx2, ry2, params, zero_ticks=3)
    assert rx3 == 0.0 and ry3 == 0.0
    print("[PASS] test_right_stick_crisp_stopping_dead passed.")


def test_zero_runaway_drift_when_aiming_or_shooting():
    """Verify right stick NEVER micro-holds or moves when mouse stops, even when LT/RT are held."""
    params = dict(DEFAULT_CONFIG)
    params["aim_assist_lock"] = True

    # Even if LT/RT are held and is_engaged is True, on zero_ticks >= 2 right stick must be strictly (0.0, 0.0)
    rx, ry = compute_right_stick(0, 0, 0.5, 0.5, params, zero_ticks=2, is_engaged=True, last_dir=(1.0, 0.0))
    assert rx == 0.0 and ry == 0.0, f"Runaway crosshair detected! Expected (0.0, 0.0), got ({rx}, {ry})"

    # From rest with LT held
    rx, ry = compute_right_stick(0, 0, 0.0, 0.0, params, zero_ticks=1, is_engaged=True)
    assert rx == 0.0 and ry == 0.0, "Right stick moved from rest while holding LT!"
    print("[PASS] test_zero_runaway_drift_when_aiming_or_shooting passed.")


def test_subtle_left_stick_micro_strafe():
    """Verify Left Stick micro-strafe oscillates subtly at ±0.07 (above 0.05 deadzone) with zero screen shake."""
    engine = Engine()
    engine.params["aim_assist_lock"] = True
    engine.lt = 1.0  # Aiming down sights (RMB)
    engine._held_vks.clear()

    engine._sync_keyboard_locked()
    assert abs(engine.lx) == 0.07, f"Expected subtle micro-strafe 0.07, got {engine.lx}"
    assert engine.ly == 0.0

    # When user actively presses 'A' (VK 0x41), player movement takes full priority
    engine._held_vks.add(0x41)  # 'A' = move_left
    engine._sync_keyboard_locked()
    assert engine.lx == -1.0, f"Player movement must override booster strafe, got {engine.lx}"

    # When triggers are released, stick returns to 0.0
    engine._held_vks.clear()
    engine.lt = 0.0
    engine.rt = 0.0
    engine._sync_keyboard_locked()
    assert engine.lx == 0.0, f"When neither LT nor RT is pressed, idle stick must be 0.0, got {engine.lx}"
    print("[PASS] test_subtle_left_stick_micro_strafe passed.")


def test_phase12_default_config_tuning():
    """Verify default configuration values match 0.05 in-game deadzone tuning."""
    assert DEFAULT_CONFIG["anti_deadzone"] == 0.06, f"Expected anti_deadzone 0.06, got {DEFAULT_CONFIG['anti_deadzone']}"
    assert DEFAULT_CONFIG["smoothing"] == 0.10, f"Expected smoothing 0.10, got {DEFAULT_CONFIG['smoothing']}"
    assert DEFAULT_CONFIG["sensitivity"] == 0.075, f"Expected sensitivity 0.075, got {DEFAULT_CONFIG['sensitivity']}"
    assert DEFAULT_CONFIG["exponent"] == 0.85, f"Expected exponent 0.85, got {DEFAULT_CONFIG['exponent']}"
    print("[PASS] test_phase12_default_config_tuning passed.")


def test_unmapped_keys_suppression():
    """Verify unmapped keys are suppressed while ACTIVE, but F8 and END are always passed through."""
    engine = Engine()
    engine.active = True
    engine.params["aim_only"] = False

    unmapped_data = MockData(0x5A)  # VK_Z
    assert engine._handle_key(WM_KEYDOWN, unmapped_data) is True, "Unmapped key must be suppressed while ACTIVE"

    f8_data = MockData(VK_F8)
    assert engine._handle_key(WM_KEYDOWN, f8_data) is False, "F8 must NEVER be suppressed"
    assert engine._handle_key(WM_KEYUP, f8_data) is False, "F8 up must NEVER be suppressed"

    end_data = MockData(VK_END)
    assert engine._handle_key(WM_KEYDOWN, end_data) is False, "END must NEVER be suppressed"

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
    test_right_stick_crisp_stopping_dead()
    test_zero_runaway_drift_when_aiming_or_shooting()
    test_subtle_left_stick_micro_strafe()
    test_phase12_default_config_tuning()
    test_unmapped_keys_suppression()
    test_app_gui_aim_lock_integration()
    print("\nALL PHASE 12 AIM ASSIST TESTS PASSED!")
