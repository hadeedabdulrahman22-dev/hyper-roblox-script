"""Unit test suite for Phase 9: Dynamic Custom Keybinds, Serialization, & Controller Mapping."""
import os
import sys
import json
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from controller_core import (
    ACTIONS,
    ACTIONS_BY_ID,
    DEFAULT_KEYBINDS,
    Engine,
    name_to_vks,
    vk_to_name,
    compute_right_stick,
    DEFAULT_CONFIG,
)
import vgamepad as vg


def test_name_and_vk_conversion():
    """Verify conversion between human-readable key names and Windows VK codes."""
    assert name_to_vks("W") == [ord("W")]
    assert name_to_vks("SPACE") == [0x20]
    assert 0xA0 in name_to_vks("LSHIFT")
    assert 0x09 in name_to_vks("TAB")

    assert vk_to_name(ord("W")) == "W"
    assert vk_to_name(0x20) == "SPACE"
    assert vk_to_name(0xA0) == "LSHIFT"
    assert vk_to_name(0x09) == "TAB"
    print("[PASS] test_name_and_vk_conversion passed.")


def test_dynamic_rebind_and_config_persistence():
    """Verify that remapping a key in Engine updates runtime lookup tables and persists to config."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_config_path = tf.name

    try:
        # 1. Initialize Engine with temporary config path
        e = Engine(config_path=temp_config_path)

        # Default Jump is SPACE (0x20)
        assert e.keybinds["jump"] == ["SPACE"]
        assert 0x20 in e._vk_to_actions
        assert "jump" in e._vk_to_actions[0x20]

        # 2. Rebind Jump to 'J'
        e.update_keybind("jump", ["J"])
        assert e.keybinds["jump"] == ["J"]

        # 0x20 should no longer trigger jump, ord('J') should trigger jump
        j_vk = ord("J")
        assert j_vk in e._vk_to_actions
        assert "jump" in e._vk_to_actions[j_vk]
        assert "jump" not in e._vk_to_actions.get(0x20, [])

        # 3. Verify file was saved to disk
        with open(temp_config_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert "keybinds" in saved
        assert saved["keybinds"]["jump"] == ["J"]

        # 4. Load a new Engine instance from that file and verify persistence
        e2 = Engine(config_path=temp_config_path)
        assert e2.keybinds["jump"] == ["J"]
        assert j_vk in e2._vk_to_actions
        assert "jump" in e2._vk_to_actions[j_vk]

        # 5. Reset to defaults
        e2.reset_keybinds_to_default()
        assert e2.keybinds["jump"] == ["SPACE"]
        assert "jump" in e2._vk_to_actions[0x20]

        # Verify disk updated on reset
        with open(temp_config_path, "r", encoding="utf-8") as f:
            saved_reset = json.load(f)
        assert saved_reset["keybinds"]["jump"] == ["SPACE"]

        print("[PASS] test_dynamic_rebind_and_config_persistence passed.")
    finally:
        if os.path.exists(temp_config_path):
            os.remove(temp_config_path)


def test_interactive_rebind_flow():
    """Verify start_rebind, finish_rebind, and cancel_rebind logic."""
    e = Engine()
    captured_result = {}

    def on_done(action_id, key_name):
        captured_result["done"] = (action_id, key_name)

    def on_cancel(action_id):
        captured_result["canceled"] = action_id

    # 1. Start rebinding 'ability_1'
    e.start_rebind("ability_1", on_done=on_done, on_cancel=on_cancel)
    assert e._rebind_action == "ability_1"

    # Finish rebind with key 'Z' (ord('Z') = 0x5A)
    e.finish_rebind(ord("Z"))
    assert e._rebind_action is None
    assert captured_result.get("done") == ("ability_1", "Z")
    assert e.keybinds["ability_1"] == ["Z"]

    # 2. Test cancel
    captured_result.clear()
    e.start_rebind("ability_1", on_done=on_done, on_cancel=on_cancel)
    e.cancel_rebind()
    assert e._rebind_action is None
    assert captured_result.get("canceled") == "ability_1"

    # Reset
    e.reset_keybinds_to_default()
    print("[PASS] test_interactive_rebind_flow passed.")


def test_controller_input_sync():
    """Verify that held VKs properly deflect Left Stick and activate Xbox buttons."""
    e = Engine()
    e.active = True

    # Press 'W' (move_forward)
    w_vk = ord("W")
    e._held_vks.add(w_vk)
    e._sync_keyboard_locked()
    assert e.ly == 1.0 and e.lx == 0.0

    # Press 'D' (move_right) alongside 'W' -> diagonal normalized
    d_vk = ord("D")
    e._held_vks.add(d_vk)
    e._sync_keyboard_locked()
    assert round(e.ly, 2) == 0.71 and round(e.lx, 2) == 0.71

    # Release 'W' and 'D'
    e._held_vks.clear()
    e._sync_keyboard_locked()
    assert e.ly == 0.0 and e.lx == 0.0

    # Press 'SPACE' -> Jump (XUSB_GAMEPAD_A)
    e._held_vks.add(0x20)
    e._sync_keyboard_locked()
    assert vg.XUSB_BUTTON.XUSB_GAMEPAD_A in e._buttons

    # Release 'SPACE'
    e._held_vks.clear()
    e._sync_keyboard_locked()
    assert vg.XUSB_BUTTON.XUSB_GAMEPAD_A not in e._buttons

    # Press 'TAB' -> Scoreboard (XUSB_GAMEPAD_DPAD_RIGHT)
    e._held_vks.add(0x09)
    e._sync_keyboard_locked()
    assert vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT in e._buttons

    e.reset_inputs()
    print("[PASS] test_controller_input_sync passed.")


def test_mouse_zero_drift_retained():
    """Verify right stick math still has zero upward drift when stationary."""
    params = dict(DEFAULT_CONFIG)
    rx, ry = compute_right_stick(0, 0, 0.0, 0.0, params)
    assert rx == 0.0 and ry == 0.0
    print("[PASS] test_mouse_zero_drift_retained passed.")


if __name__ == "__main__":
    print("Running Phase 9 Test Suite...")
    test_name_and_vk_conversion()
    test_dynamic_rebind_and_config_persistence()
    test_interactive_rebind_flow()
    test_controller_input_sync()
    test_mouse_zero_drift_retained()
    print("\nALL PHASE 9 TESTS PASSED SUCCESSFULLY!")
