"""Unit and regression tests for aim math, zero drift, and Hypershot controller mappings."""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from controller_core import (
    DEFAULT_CONFIG,
    BUTTON_BINDINGS,
    BUTTON_MAP,
    VK_TO_KEY,
    compute_right_stick,
)
import vgamepad as vg


def test_zero_drift_when_mouse_stationary():
    """Verify that when dx=0 and dy=0, right stick (rx, ry) is strictly (0.0, 0.0) with ZERO upward drift."""
    params = dict(DEFAULT_CONFIG)

    # 1. From complete rest
    rx, ry = compute_right_stick(0, 0, 0.0, 0.0, params)
    assert rx == 0.0 and ry == 0.0, f"Expected (0.0, 0.0), got ({rx}, {ry})"
    assert ry <= 0.0, f"Upward drift detected: ry={ry}"

    # 2. When stopping after aiming up
    rx, ry = compute_right_stick(0, 0, 0.0, 0.95, params)
    assert rx == 0.0 and ry == 0.0, f"Expected immediate snap to (0.0, 0.0), got ({rx}, {ry})"

    # 3. When stopping after aiming right/down
    rx, ry = compute_right_stick(0, 0, 0.75, -0.65, params)
    assert rx == 0.0 and ry == 0.0, f"Expected immediate snap to (0.0, 0.0), got ({rx}, {ry})"

    # 4. Multi-tick rest test (simulating 10 ticks at 120Hz while mouse is still)
    cur_rx, cur_ry = 0.0, 0.0
    for _ in range(10):
        cur_rx, cur_ry = compute_right_stick(0, 0, cur_rx, cur_ry, params)
        assert cur_rx == 0.0 and cur_ry == 0.0, f"Drift occurred during rest: ({cur_rx}, {cur_ry})"

    print("[PASS] test_zero_drift_when_mouse_stationary passed.")


def test_aim_directionality():
    """Verify standard FPS mouse to right-stick coordinate translation."""
    params = dict(DEFAULT_CONFIG)

    # Moving right (dx > 0) -> RS X positive (look right)
    rx, ry = compute_right_stick(15, 0, 0.0, 0.0, params)
    assert rx > 0.0, f"Expected rx > 0 for rightward mouse move, got {rx}"
    assert ry == 0.0, f"Expected ry == 0 for pure horizontal move, got {ry}"

    # Moving left (dx < 0) -> RS X negative (look left)
    rx, ry = compute_right_stick(-15, 0, 0.0, 0.0, params)
    assert rx < 0.0, f"Expected rx < 0 for leftward mouse move, got {rx}"
    assert ry == 0.0, f"Expected ry == 0 for pure horizontal move, got {ry}"

    # Moving mouse forward/away from user in Windows: dy < 0 -> RS Y positive (look UP)
    rx, ry = compute_right_stick(0, -15, 0.0, 0.0, params)
    assert ry > 0.0, f"Expected ry > 0 (look up) for forward mouse move, got {ry}"
    assert rx == 0.0, f"Expected rx == 0 for pure vertical move, got {rx}"

    # Moving mouse backward/toward user: dy > 0 -> RS Y negative (look DOWN)
    rx, ry = compute_right_stick(0, 15, 0.0, 0.0, params)
    assert ry < 0.0, f"Expected ry < 0 (look down) for backward mouse move, got {ry}"
    assert rx == 0.0, f"Expected rx == 0 for pure vertical move, got {rx}"

    # Invert Y test
    inv_params = dict(params, invert_y=True)
    rx, ry = compute_right_stick(0, -15, 0.0, 0.0, inv_params)
    assert ry < 0.0, f"Expected inverted ry < 0 (look down) for forward move, got {ry}"

    print("[PASS] test_aim_directionality passed.")


def test_hypershot_hud_mappings():
    """Verify all key-to-controller button mappings match the Hypershot controller HUD."""
    # 1. Ability 1 (Q) -> LB / L1
    assert "q" in BUTTON_BINDINGS["LB"], "Q must map to LB (L1 Ability 1)"
    assert BUTTON_MAP["LB"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER

    # 2. Ability 2 (E) -> RB / R1
    assert "e" in BUTTON_BINDINGS["RB"], "E must map to RB (R1 Ability 2)"
    assert BUTTON_MAP["RB"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER

    # 3. Ability 3 / Ultimate (X) -> B
    assert "x" in BUTTON_BINDINGS["B"], "X must map to B (Ability 3 / Ultimate)"
    assert BUTTON_MAP["B"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_B

    # 4. Slide (C and Left Shift) -> L3
    assert "c" in BUTTON_BINDINGS["L3"] and "shift" in BUTTON_BINDINGS["L3"], "C and Shift must map to L3 (Slide)"
    assert BUTTON_MAP["L3"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB

    # 5. Quick Melee (F) -> R3
    assert "f" in BUTTON_BINDINGS["R3"], "F must map to R3 (Quick Melee)"
    assert BUTTON_MAP["R3"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB

    # 6. Reload & Inspect (R and V) -> X
    assert "r" in BUTTON_BINDINGS["X"] and "v" in BUTTON_BINDINGS["X"], "R and V must map to X (Reload / Inspect)"
    assert BUTTON_MAP["X"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_X

    # 7. Swap Weapons 1 & 2 -> Y
    assert "1" in BUTTON_BINDINGS["Y"] and "2" in BUTTON_BINDINGS["Y"], "1 and 2 must map to Y (Weapon Swap)"
    assert BUTTON_MAP["Y"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_Y

    # 8. Slot 3 / Knife -> DPAD_UP
    assert "3" in BUTTON_BINDINGS["DPAD_UP"], "3 must map to DPAD_UP (Slot 3 Melee Equip)"
    assert BUTTON_MAP["DPAD_UP"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP

    # 9. Jump (Space) -> A
    assert "space" in BUTTON_BINDINGS["A"], "Space must map to A (Jump)"
    assert BUTTON_MAP["A"] == vg.XUSB_BUTTON.XUSB_GAMEPAD_A

    # 10. Check V is registered in VK_TO_KEY
    assert ord("V") in VK_TO_KEY and VK_TO_KEY[ord("V")] == "v", "V key must be in VK_TO_KEY"

    print("[PASS] test_hypershot_hud_mappings passed.")


if __name__ == "__main__":
    print("Running verification suite...")
    test_zero_drift_when_mouse_stationary()
    test_aim_directionality()
    test_hypershot_hud_mappings()
    print("\nALL TESTS PASSED SUCCESSFULLY!")
