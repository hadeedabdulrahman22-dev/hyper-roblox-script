"""Unit test suite for Phase 10: Interactive Visual Xbox Controller Diagram & Coordinate Blueprint."""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from controller_core import Engine
from app import ControllerApp
import tkinter as tk


def test_controller_diagram_initialization():
    """Verify ControllerApp initializes the 500x380 canvas and all blueprint elements."""
    engine = Engine()
    app = ControllerApp(engine)

    # 1. Verify canvas properties
    assert app.canvas is not None, "Canvas must be created"
    assert int(app.canvas.cget("width")) == 500, "Canvas width must be 500"
    assert int(app.canvas.cget("height")) == 380, "Canvas height must be 380"

    # 2. Verify all required diagram item IDs exist
    required_keys = [
        "btn_LT", "text_LT", "btn_RT", "text_RT",
        "btn_LB", "text_LB", "btn_RB", "text_RB",
        "cap_LS", "text_LS", "lbl_L3",
        "btn_back", "lbl_back", "btn_start", "lbl_start",
        "btn_Y", "text_Y", "lbl_Y",
        "btn_X", "text_X", "lbl_X",
        "btn_B", "text_B", "lbl_B",
        "btn_A", "text_A", "lbl_A",
        "dpad_up", "dpad_down", "dpad_left", "dpad_right",
        "lbl_dpad_up", "lbl_dpad_down", "lbl_dpad_left", "lbl_dpad_right",
        "cap_RS", "text_RS", "lbl_R3"
    ]
    for k in required_keys:
        assert k in app.diagram_items, f"Missing diagram item: {k}"

    print("[PASS] test_controller_diagram_initialization passed.")
    app.on_closing()


def test_dynamic_diagram_label_updates():
    """Verify that remapping keybinds dynamically updates the text on the diagram canvas."""
    engine = Engine()
    app = ControllerApp(engine)

    # Initially Jump is SPACE
    space_label = app.canvas.itemcget(app.diagram_items["lbl_A"], "text")
    assert "SPACE" in space_label

    # Rebind Jump to 'J'
    engine.update_keybind("jump", ["J"])
    app.refresh_diagram_labels()

    updated_label = app.canvas.itemcget(app.diagram_items["lbl_A"], "text")
    assert "J" in updated_label, f"Expected 'J', got {updated_label}"

    # Rebind Ability 1 to 'Z'
    engine.update_keybind("ability_1", ["Z"])
    app.refresh_diagram_labels()
    lb_text = app.canvas.itemcget(app.diagram_items["text_LB"], "text")
    assert "Z" in lb_text, f"Expected 'Z', got {lb_text}"

    # Reset
    engine.reset_keybinds_to_default()
    app.refresh_diagram_labels()

    reset_label = app.canvas.itemcget(app.diagram_items["lbl_A"], "text")
    assert "SPACE" in reset_label

    print("[PASS] test_dynamic_diagram_label_updates passed.")
    app.on_closing()


def test_live_diagram_glow_and_deflection():
    """Verify that _update_diagram_glow responds to button presses and stick deflections."""
    engine = Engine()
    app = ControllerApp(engine)

    # 1. Simulate button presses
    snapshot_active = {
        "buttons": ["A", "LB", "DPAD_UP", "START", "L3"],
        "lt": 0.8,
        "rt": 1.0,
        "lx": 1.0, "ly": 0.0,
        "rx": 0.0, "ry": 1.0,
    }
    app._update_diagram_glow(snapshot_active)

    # 'A' button should glow neon green (#00E676)
    fill_a = app.canvas.itemcget(app.diagram_items["btn_A"], "fill")
    assert fill_a.upper() == "#00E676", f"Expected #00E676 for active A button, got {fill_a}"

    # 'LT' trigger should glow blue (#3498DB)
    fill_lt = app.canvas.itemcget(app.diagram_items["btn_LT"], "fill")
    assert fill_lt.upper() == "#3498DB", f"Expected #3498DB for active LT trigger, got {fill_lt}"

    # 'RT' trigger should glow red (#E74C3C)
    fill_rt = app.canvas.itemcget(app.diagram_items["btn_RT"], "fill")
    assert fill_rt.upper() == "#E74C3C", f"Expected #E74C3C for active RT trigger, got {fill_rt}"

    # Left Stick cap should shift horizontally for lx=1.0
    coords_ls = app.canvas.coords(app.diagram_items["cap_LS"])
    # Normal center is 115..155, with +8 offset x should be 123..163
    assert coords_ls[0] == 123.0 and coords_ls[2] == 163.0

    # 2. Simulate return to neutral
    snapshot_neutral = {
        "buttons": [],
        "lt": 0.0,
        "rt": 0.0,
        "lx": 0.0, "ly": 0.0,
        "rx": 0.0, "ry": 0.0,
    }
    app._update_diagram_glow(snapshot_neutral)

    fill_a_neutral = app.canvas.itemcget(app.diagram_items["btn_A"], "fill")
    assert fill_a_neutral.upper() != "#00E676", "A button should revert from active glow"

    coords_ls_neutral = app.canvas.coords(app.diagram_items["cap_LS"])
    assert coords_ls_neutral[0] == 115.0 and coords_ls_neutral[2] == 155.0

    print("[PASS] test_live_diagram_glow_and_deflection passed.")
    app.on_closing()


if __name__ == "__main__":
    print("Running Phase 10 Diagram Test Suite...")
    test_controller_diagram_initialization()
    test_dynamic_diagram_label_updates()
    test_live_diagram_glow_and_deflection()
    print("\nALL PHASE 10 TESTS PASSED SUCCESSFULLY!")
