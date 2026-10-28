"""KBM-to-XInput Virtual Controller - Phase 10 Interactive Controller Map & Diagram."""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def fatal(title, message):
    """Show a readable error window AND print it, then exit."""
    print(f"\n[ERROR] {title}\n{message}\n")
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass
    sys.exit(1)


try:
    import customtkinter as ctk
    from controller_core import (
        ACTIONS,
        CONFIG_PATH,
        DEFAULT_KEYBINDS,
        LIMITS,
        Engine,
        get_connected_xinput_slot,
    )
except Exception as exc:
    fatal(
        "Missing component",
        f"{exc}\n\nClose this and start the app with run_controller.bat "
        "(it installs everything needed on first run).",
    )


class ControllerApp(ctk.CTk):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._closing = False
        self.current_rebind_id = None
        self.key_buttons = {}
        self.diagram_items = {}
        self.canvas = None

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.title("KBM-to-XInput Virtual Controller (Phase 11)")
        self.geometry("560x900")
        self.resizable(False, False)
        self.attributes("-topmost", engine.params["always_on_top"])
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.create_widgets()
        self.engine.start()
        self.update_telemetry()

    # ------------------------------------------------------------------ UI Setup
    def create_widgets(self):
        p = self.engine.params

        # 1. Top Status banner (persistent above tabs)
        self.status_frame = ctk.CTkFrame(self, corner_radius=12, border_width=2)
        self.status_frame.pack(fill="x", padx=16, pady=(10, 4))

        self.status_label = ctk.CTkLabel(
            self.status_frame, text="STATUS: PAUSED (Press F8)",
            font=ctk.CTkFont(size=17, weight="bold"))
        self.status_label.pack(pady=(6, 2))

        ctk.CTkLabel(
            self.status_frame,
            text="[F8] Toggle Active/Paused   |   [END] Emergency Kill-Switch",
            font=ctk.CTkFont(size=11), text_color="#A0A0A0").pack(pady=(0, 2))

        # XInput Slot Status Indicator
        self.slot_label = ctk.CTkLabel(
            self.status_frame,
            text="XInput Status: Checking...",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#00E676")
        self.slot_label.pack(pady=(0, 6))

        # 2. "3s Auto-Controller Test" Button (Bright & Prominent)
        self.auto_test_btn = ctk.CTkButton(
            self,
            text="3s Auto-Controller Test (Click, then focus Roblox)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1F6AA5",
            hover_color="#144870",
            height=34,
            command=self.on_auto_test
        )
        self.auto_test_btn.pack(fill="x", padx=16, pady=(2, 6))

        # 3. Tabview: 3 Tabs (Controller Map, Aim & Tuning, Custom Keybinds)
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=16, pady=(2, 10))

        tab_map = self.tabview.add("🎮 Controller Map")
        tab_aim = self.tabview.add("Aim & Tuning")
        tab_keys = self.tabview.add("Custom Keybinds")

        self._build_map_tab(tab_map)
        self._build_aim_tab(tab_aim, p)
        self._build_keybinds_tab(tab_keys)

        # Start on Controller Map tab so diagram is front and center
        self.tabview.set("🎮 Controller Map")

    # ----------------------------------------------------------- Helper: Key String
    def _key_str(self, action_id, default=""):
        keys = self.engine.keybinds.get(action_id, [])
        if not keys:
            return default
        return "/".join(keys) if len(keys) > 1 else keys[0]

    # ----------------------------------------------------------- Tab 1: Visual Controller Map
    def _build_map_tab(self, parent):
        # Top banner with title and shortcut button
        top_bar = ctk.CTkFrame(parent, fg_color="transparent")
        top_bar.pack(fill="x", padx=6, pady=(2, 4))

        ctk.CTkLabel(
            top_bar,
            text="Interactive Xbox 360 Controller Blueprint",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#00E676"
        ).pack(side="left", pady=2)

        ctk.CTkButton(
            top_bar,
            text="Rebind Keys ➡️",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=110,
            height=26,
            fg_color="#2D3748",
            hover_color="#4A5568",
            command=lambda: self.tabview.set("Custom Keybinds")
        ).pack(side="right", pady=2)

        # 500x380 Canvas Container Frame
        canvas_frame = ctk.CTkFrame(parent, fg_color="#121518", corner_radius=10)
        canvas_frame.pack(padx=4, pady=(2, 4))

        self.canvas = tk.Canvas(
            canvas_frame,
            width=500,
            height=380,
            bg="#16191D",
            highlightthickness=0
        )
        self.canvas.pack(padx=4, pady=4)

        c = self.canvas

        # 1. Controller Body Silhouette (22-point smooth spline)
        body_points = [
            110, 95, 88, 105, 62, 168, 72, 270, 88, 342, 112, 356, 134, 345, 156, 285,
            205, 270, 250, 275, 295, 270, 344, 285, 366, 345, 388, 356, 412, 342,
            428, 270, 438, 168, 412, 105, 390, 95, 290, 102, 250, 105, 210, 102
        ]
        c.create_polygon(body_points, fill="#23272E", outline="#3E4451", width=2, smooth=True)

        # 2. Trigger/Bumper Connector Lines
        c.create_line(135, 48, 135, 54, fill="#5E81AC", width=2)
        c.create_line(365, 48, 365, 54, fill="#5E81AC", width=2)

        # 3. Triggers (LT & RT)
        self.diagram_items["btn_LT"] = c.create_rectangle(
            85, 16, 185, 48, fill="#252B35", outline="#3498DB", width=2)
        self.diagram_items["text_LT"] = c.create_text(
            135, 32, text="LT: RMB (Aim)", fill="#E0E6ED", font=("Segoe UI", 9, "bold"))

        self.diagram_items["btn_RT"] = c.create_rectangle(
            315, 16, 415, 48, fill="#252B35", outline="#E74C3C", width=2)
        self.diagram_items["text_RT"] = c.create_text(
            365, 32, text="RT: LMB (Shoot)", fill="#E0E6ED", font=("Segoe UI", 9, "bold"))

        # 4. Bumpers (LB & RB)
        self.diagram_items["btn_LB"] = c.create_rectangle(
            85, 54, 185, 82, fill="#2E3440", outline="#5E81AC", width=1)
        self.diagram_items["text_LB"] = c.create_text(
            135, 68, text="LB/L1: Q", fill="#E0E6ED", font=("Segoe UI", 9, "bold"))

        self.diagram_items["btn_RB"] = c.create_rectangle(
            315, 54, 415, 82, fill="#2E3440", outline="#5E81AC", width=1)
        self.diagram_items["text_RB"] = c.create_text(
            365, 68, text="RB/R1: E", fill="#E0E6ED", font=("Segoe UI", 9, "bold"))

        # 5. Left Analog Stick (x=135, y=155)
        c.create_oval(107, 127, 163, 183, fill="#191C20", outline="#3E4451", width=2)
        self.diagram_items["cap_LS"] = c.create_oval(
            115, 135, 155, 175, fill="#282C34", outline="#5E81AC", width=2)
        self.diagram_items["text_LS"] = c.create_text(
            135, 155, text="WASD", fill="#FFFFFF", font=("Segoe UI", 10, "bold"))
        c.create_text(135, 118, text="Left Stick", fill="#88C0D0", font=("Segoe UI", 8, "bold"))
        self.diagram_items["lbl_L3"] = c.create_text(
            135, 195, text="L3: C / LSHIFT", fill="#EBCB8B", font=("Segoe UI", 8, "bold"))

        # 6. Back & Start Buttons
        self.diagram_items["btn_back"] = c.create_oval(
            203, 133, 227, 157, fill="#2D333B", outline="#4C566A", width=2)
        c.create_text(215, 145, text="Back", fill="#E0E6ED", font=("Segoe UI", 7, "bold"))
        self.diagram_items["lbl_back"] = c.create_text(
            215, 166, text="Back: M", fill="#A0A0A0", font=("Segoe UI", 8, "bold"))

        self.diagram_items["btn_start"] = c.create_oval(
            273, 133, 297, 157, fill="#2D333B", outline="#4C566A", width=2)
        c.create_text(285, 145, text="Start", fill="#E0E6ED", font=("Segoe UI", 7, "bold"))
        self.diagram_items["lbl_start"] = c.create_text(
            285, 166, text="Start: K", fill="#A0A0A0", font=("Segoe UI", 8, "bold"))

        # 7. Center Xbox Jewel Logo
        c.create_oval(236, 124, 264, 152, fill="#1E2227", outline="#00E676", width=2)
        c.create_text(250, 138, text="X", fill="#00E676", font=("Segoe UI", 12, "bold"))

        # 8. ABXY Face Buttons Cluster (Diamond around x=365, y=152)
        # Y Button (Top: x=365, y=122)
        self.diagram_items["btn_Y"] = c.create_oval(
            353, 110, 377, 134, fill="#2A2715", outline="#F1C40F", width=2)
        self.diagram_items["text_Y"] = c.create_text(
            365, 122, text="Y", fill="#F1C40F", font=("Segoe UI", 10, "bold"))
        self.diagram_items["lbl_Y"] = c.create_text(
            400, 122, text="1, 2", fill="#F1C40F", font=("Segoe UI", 8, "bold"))

        # X Button (Left: x=335, y=152)
        self.diagram_items["btn_X"] = c.create_oval(
            323, 140, 347, 164, fill="#142230", outline="#3498DB", width=2)
        self.diagram_items["text_X"] = c.create_text(
            335, 152, text="X", fill="#3498DB", font=("Segoe UI", 10, "bold"))
        self.diagram_items["lbl_X"] = c.create_text(
            304, 152, text="R, V", fill="#3498DB", font=("Segoe UI", 8, "bold"))

        # B Button (Right: x=395, y=152)
        self.diagram_items["btn_B"] = c.create_oval(
            383, 140, 407, 164, fill="#2D1818", outline="#E74C3C", width=2)
        self.diagram_items["text_B"] = c.create_text(
            395, 152, text="B", fill="#E74C3C", font=("Segoe UI", 10, "bold"))
        self.diagram_items["lbl_B"] = c.create_text(
            424, 152, text="X", fill="#E74C3C", font=("Segoe UI", 8, "bold"))

        # A Button (Bottom: x=365, y=182)
        self.diagram_items["btn_A"] = c.create_oval(
            353, 170, 377, 194, fill="#12261A", outline="#2ECC71", width=2)
        self.diagram_items["text_A"] = c.create_text(
            365, 182, text="A", fill="#2ECC71", font=("Segoe UI", 10, "bold"))
        self.diagram_items["lbl_A"] = c.create_text(
            365, 203, text="SPACE", fill="#2ECC71", font=("Segoe UI", 8, "bold"))

        # 9. D-Pad Directional Pad (x=185, y=255)
        self.diagram_items["dpad_up"] = c.create_rectangle(
            176, 233, 194, 255, fill="#252A30", outline="#4C566A")
        self.diagram_items["dpad_down"] = c.create_rectangle(
            176, 255, 194, 277, fill="#252A30", outline="#4C566A")
        self.diagram_items["dpad_left"] = c.create_rectangle(
            163, 246, 185, 264, fill="#252A30", outline="#4C566A")
        self.diagram_items["dpad_right"] = c.create_rectangle(
            185, 246, 207, 264, fill="#252A30", outline="#4C566A")
        c.create_oval(179, 249, 191, 261, fill="#1E2227", outline="#3E4451")

        self.diagram_items["lbl_dpad_up"] = c.create_text(
            185, 222, text="Up: 3", fill="#88C0D0", font=("Segoe UI", 8, "bold"))
        self.diagram_items["lbl_dpad_left"] = c.create_text(
            138, 255, text="L: B", fill="#88C0D0", font=("Segoe UI", 8, "bold"))
        self.diagram_items["lbl_dpad_right"] = c.create_text(
            232, 255, text="R: TAB", fill="#88C0D0", font=("Segoe UI", 8, "bold"))
        self.diagram_items["lbl_dpad_down"] = c.create_text(
            185, 288, text="Down: H", fill="#88C0D0", font=("Segoe UI", 8, "bold"))

        # 10. Right Analog Stick (x=315, y=255)
        c.create_oval(287, 227, 343, 283, fill="#191C20", outline="#3E4451", width=2)
        self.diagram_items["cap_RS"] = c.create_oval(
            295, 235, 335, 275, fill="#282C34", outline="#88C0D0", width=2)
        self.diagram_items["text_RS"] = c.create_text(
            315, 255, text="Mouse", fill="#FFFFFF", font=("Segoe UI", 10, "bold"))
        c.create_text(315, 218, text="Right Stick (Aim)", fill="#88C0D0", font=("Segoe UI", 8, "bold"))
        self.diagram_items["lbl_R3"] = c.create_text(
            315, 295, text="R3: F Melee", fill="#EBCB8B", font=("Segoe UI", 8, "bold"))

        # Initialize canvas labels with current bindings
        self.refresh_diagram_labels()

        # Bottom Quick Reference Banner
        quick_frame = ctk.CTkFrame(parent, fg_color="#18232C", corner_radius=8)
        quick_frame.pack(fill="x", padx=6, pady=(2, 6))

        ctk.CTkLabel(
            quick_frame,
            text="💡 Live Diagnostic: Buttons glow when pressed & sticks deflect with WASD / Mouse movement!",
            font=ctk.CTkFont(size=11),
            text_color="#88C0D0"
        ).pack(anchor="w", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            quick_frame,
            text="Primary Controls:  WASD = Left Stick  |  Mouse = Right Stick  |  LMB = RT Shoot  |  RMB = LT Aim",
            font=ctk.CTkFont(size=10),
            text_color="#A0A0A0"
        ).pack(anchor="w", padx=10, pady=(0, 6))

    def refresh_diagram_labels(self):
        """Update all text labels on the controller diagram to match active keybinds."""
        if not self.canvas:
            return
        c = self.canvas

        c.itemconfig(self.diagram_items["text_LB"],
                     text=f"LB/L1: {self._key_str('ability_1', 'Q')}")
        c.itemconfig(self.diagram_items["text_RB"],
                     text=f"RB/R1: {self._key_str('ability_2', 'E')}")

        c.itemconfig(self.diagram_items["lbl_L3"],
                     text=f"L3: {self._key_str('slide', 'C/LSHIFT')}")
        c.itemconfig(self.diagram_items["lbl_R3"],
                     text=f"R3: {self._key_str('quick_melee', 'F')} Melee")

        c.itemconfig(self.diagram_items["lbl_back"],
                     text=f"Back: {self._key_str('cursor_back', 'M')}")
        c.itemconfig(self.diagram_items["lbl_start"],
                     text=f"Start: {self._key_str('menu_start', 'K')}")

        c.itemconfig(self.diagram_items["lbl_Y"],
                     text=self._key_str("swap_weapons", "1, 2"))
        c.itemconfig(self.diagram_items["lbl_X"],
                     text=self._key_str("reload", "R, V"))
        c.itemconfig(self.diagram_items["lbl_B"],
                     text=self._key_str("ability_3", "X"))
        c.itemconfig(self.diagram_items["lbl_A"],
                     text=self._key_str("jump", "SPACE"))

        c.itemconfig(self.diagram_items["lbl_dpad_up"],
                     text=f"Up: {self._key_str('equip_melee', '3')}")
        c.itemconfig(self.diagram_items["lbl_dpad_left"],
                     text=f"L: {self._key_str('emote', 'B')}")
        c.itemconfig(self.diagram_items["lbl_dpad_right"],
                     text=f"R: {self._key_str('scoreboard', 'TAB')}")
        c.itemconfig(self.diagram_items["lbl_dpad_down"],
                     text=f"Down: {self._key_str('dpad_down', 'H')}")

    def _update_diagram_glow(self, s):
        """Highlight active buttons and shift thumbstick positions in real time."""
        if not self.canvas:
            return
        c = self.canvas
        btns = set(s.get("buttons", []))

        # ABXY Face Buttons
        c.itemconfig(self.diagram_items["btn_A"],
                     fill="#00E676" if "A" in btns else "#12261A")
        c.itemconfig(self.diagram_items["btn_B"],
                     fill="#FF3333" if "B" in btns else "#2D1818")
        c.itemconfig(self.diagram_items["btn_X"],
                     fill="#00B0FF" if "X" in btns else "#142230")
        c.itemconfig(self.diagram_items["btn_Y"],
                     fill="#FFD700" if "Y" in btns else "#2A2715")

        # Bumpers
        c.itemconfig(self.diagram_items["btn_LB"],
                     fill="#00E676" if "LB" in btns else "#2E3440")
        c.itemconfig(self.diagram_items["btn_RB"],
                     fill="#00E676" if "RB" in btns else "#2E3440")

        # Triggers (glow blue on aim, glow red on shoot)
        c.itemconfig(self.diagram_items["btn_LT"],
                     fill="#3498DB" if s.get("lt", 0) > 0.05 else "#252B35")
        c.itemconfig(self.diagram_items["btn_RT"],
                     fill="#E74C3C" if s.get("rt", 0) > 0.05 else "#252B35")

        # D-Pad Arms
        c.itemconfig(self.diagram_items["dpad_up"],
                     fill="#00E676" if "DPAD_UP" in btns else "#252A30")
        c.itemconfig(self.diagram_items["dpad_down"],
                     fill="#00E676" if "DPAD_DOWN" in btns else "#252A30")
        c.itemconfig(self.diagram_items["dpad_left"],
                     fill="#00E676" if "DPAD_LEFT" in btns else "#252A30")
        c.itemconfig(self.diagram_items["dpad_right"],
                     fill="#00E676" if "DPAD_RIGHT" in btns else "#252A30")

        # Start / Back
        c.itemconfig(self.diagram_items["btn_start"],
                     fill="#00E676" if "START" in btns else "#2D333B")
        c.itemconfig(self.diagram_items["btn_back"],
                     fill="#00E676" if "BACK" in btns else "#2D333B")

        # Stick Click (L3 / R3)
        c.itemconfig(self.diagram_items["cap_LS"],
                     fill="#00E676" if "L3" in btns else "#282C34")
        c.itemconfig(self.diagram_items["cap_RS"],
                     fill="#00E676" if "R3" in btns else "#282C34")

        # Dynamic Thumbstick Deflection
        lx, ly = s.get("lx", 0.0), s.get("ly", 0.0)
        ls_dx = round(lx * 8)
        ls_dy = round(-ly * 8)
        c.coords(self.diagram_items["cap_LS"], 115 + ls_dx, 135 + ls_dy, 155 + ls_dx, 175 + ls_dy)
        c.coords(self.diagram_items["text_LS"], 135 + ls_dx, 155 + ls_dy)

        rx, ry = s.get("rx", 0.0), s.get("ry", 0.0)
        rs_dx = round(rx * 8)
        rs_dy = round(-ry * 8)
        c.coords(self.diagram_items["cap_RS"], 295 + rs_dx, 235 + rs_dy, 335 + rs_dx, 275 + rs_dy)
        c.coords(self.diagram_items["text_RS"], 315 + rs_dx, 255 + rs_dy)

    # ----------------------------------------------------------- Tab 2: Aim & Tuning
    def _build_aim_tab(self, parent, p):
        mode = ctk.CTkFrame(parent, corner_radius=10)
        mode.pack(fill="x", padx=4, pady=4)

        self.aim_only_var = ctk.BooleanVar(value=p["aim_only"])
        ctk.CTkSwitch(
            mode, text="Aim-Only Mode (Mouse -> Right Stick Only)",
            variable=self.aim_only_var, font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_aim_only_toggle).pack(anchor="w", padx=14, pady=(8, 2))
        ctk.CTkLabel(
            mode, text="Off = Full Controller Mode (keyboard + mouse both become controller)",
            font=ctk.CTkFont(size=10), text_color="#888888").pack(anchor="w", padx=14, pady=(0, 6))

        row1 = ctk.CTkFrame(mode, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(0, 4))
        self.topmost_var = ctk.BooleanVar(value=p["always_on_top"])
        ctk.CTkCheckBox(row1, text="Always on Top", variable=self.topmost_var,
                        command=self.on_topmost_toggle).pack(side="left", padx=(0, 20))
        self.invert_y_var = ctk.BooleanVar(value=p["invert_y"])
        ctk.CTkCheckBox(row1, text="Invert Y-Axis", variable=self.invert_y_var,
                        command=self.on_invert_y_toggle).pack(side="left")

        # Row 2 Checkboxes: Block Physical Mouse Move & Rotational Booster
        self.block_mouse_var = ctk.BooleanVar(value=p.get("block_mouse_move", True))
        ctk.CTkCheckBox(
            mode,
            text="Block Physical Mouse Move (Recommended - Freeze Cursor)",
            variable=self.block_mouse_var,
            command=self.on_block_mouse_toggle
        ).pack(anchor="w", padx=14, pady=(4, 4))

        self.booster_var = ctk.BooleanVar(value=p.get("rotational_booster", True))
        ctk.CTkCheckBox(
            mode,
            text="Rotational Aim Assist Booster (Keep Stick Engaged on LT/RT)",
            variable=self.booster_var,
            command=self.on_booster_toggle
        ).pack(anchor="w", padx=14, pady=(2, 8))

        # Sliders
        sliders = ctk.CTkFrame(parent, corner_radius=10)
        sliders.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(sliders, text="Mouse Aim & Curve Tuning",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=14, pady=(6, 4))

        self.sens_label, self.sens_slider = self._slider(
            sliders, "sensitivity", "Sensitivity", 3, 145)
        self.dz_label, self.dz_slider = self._slider(
            sliders, "anti_deadzone", "Anti-Deadzone Boost", 2, 35)
        self.expo_label, self.expo_slider = self._slider(
            sliders, "exponent", "Response Exponent", 2, 110)
        self.smooth_label, self.smooth_slider = self._slider(
            sliders, "smoothing", "Smoothing (Anti-Jitter)", 2, 85, pad_bottom=8)

        # Telemetry
        telem = ctk.CTkFrame(parent, corner_radius=10)
        telem.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(telem, text="Live Virtual Controller Telemetry",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=14, pady=(6, 2))
        mono = ctk.CTkFont(family="Consolas", size=11)
        self.stick_label = ctk.CTkLabel(telem, text="", font=mono)
        self.stick_label.pack(anchor="w", padx=14, pady=1)
        self.trigger_label = ctk.CTkLabel(telem, text="", font=mono, text_color="#88C0D0")
        self.trigger_label.pack(anchor="w", padx=14, pady=1)
        self.mouse_label = ctk.CTkLabel(telem, text="", font=mono, text_color="#EBCB8B")
        self.mouse_label.pack(anchor="w", padx=14, pady=(1, 6))

        # Save Settings
        action = ctk.CTkFrame(parent, fg_color="transparent")
        action.pack(fill="x", padx=4, pady=(4, 6))
        ctk.CTkButton(action, text="Save Settings (config.json)",
                      font=ctk.CTkFont(size=13, weight="bold"), height=34,
                      command=self.on_save_settings).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.save_status = ctk.CTkLabel(action, text="", text_color="#00E676",
                                        font=ctk.CTkFont(size=12, weight="bold"))
        self.save_status.pack(side="right")

    # ----------------------------------------------------------- Tab 3: Custom Keybinds
    def _build_keybinds_tab(self, parent):
        top_bar = ctk.CTkFrame(parent, fg_color="transparent")
        top_bar.pack(fill="x", padx=4, pady=(2, 4))

        ctk.CTkLabel(
            top_bar,
            text="🎮 Click any key button to rebind (ESC to cancel)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00E676"
        ).pack(side="left", pady=2)

        ctk.CTkButton(
            top_bar,
            text="Reset to Defaults",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#C0392B",
            hover_color="#962D22",
            height=28,
            width=130,
            command=self.on_reset_keybinds
        ).pack(side="right", pady=2)

        # Scrollable area listing all actions
        self.key_scroll = ctk.CTkScrollableFrame(parent, corner_radius=8, height=480)
        self.key_scroll.pack(fill="both", expand=True, padx=2, pady=(2, 6))

        categories = [
            ("Movement", "🕹️ Left Analog Stick Movement"),
            ("Combat", "⚔️ Combat, Abilities & Weaponry"),
            ("Menus", "📋 Navigation, Menus & Emotes"),
        ]

        for cat_id, cat_title in categories:
            cat_actions = [a for a in ACTIONS if a.get("category") == cat_id]
            if not cat_actions:
                continue

            # Category Header
            cat_hdr = ctk.CTkFrame(self.key_scroll, fg_color="#18232C", corner_radius=6)
            cat_hdr.pack(fill="x", pady=(8, 4), padx=2)
            ctk.CTkLabel(
                cat_hdr,
                text=cat_title,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#88C0D0"
            ).pack(anchor="w", padx=10, pady=4)

            # Action Rows
            for act in cat_actions:
                aid = act["id"]
                row = ctk.CTkFrame(self.key_scroll, fg_color="#1F1F1F", corner_radius=6)
                row.pack(fill="x", pady=2, padx=2)

                # Action Name
                ctk.CTkLabel(
                    row,
                    text=act["name"],
                    font=ctk.CTkFont(size=12, weight="bold"),
                    anchor="w",
                    width=170
                ).pack(side="left", padx=(10, 6), pady=6)

                # Xbox Badge
                badge = ctk.CTkFrame(row, fg_color="#2A2A2A", corner_radius=6)
                badge.pack(side="left", padx=4, pady=6)
                ctk.CTkLabel(
                    badge,
                    text=act["xbox"],
                    font=ctk.CTkFont(size=11),
                    text_color="#EBCB8B",
                    width=120
                ).pack(padx=6, pady=2)

                # Rebind Button
                current_keys = self.engine.keybinds.get(aid, act["default"])
                key_text = ", ".join(current_keys)
                btn = ctk.CTkButton(
                    row,
                    text=key_text,
                    font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                    fg_color="#2D3748",
                    hover_color="#4A5568",
                    width=130,
                    height=28,
                    command=lambda a=aid: self.on_start_rebind(a)
                )
                btn.pack(side="right", padx=(6, 10), pady=6)
                self.key_buttons[aid] = btn

        # Bottom save & feedback bar for Tab 3
        key_save_bar = ctk.CTkFrame(parent, fg_color="transparent")
        key_save_bar.pack(fill="x", padx=4, pady=(2, 6))

        ctk.CTkButton(
            key_save_bar,
            text="Save Keybinds (config.json)",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=34,
            command=self.on_save_settings
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.key_save_status = ctk.CTkLabel(
            key_save_bar,
            text="",
            text_color="#00E676",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.key_save_status.pack(side="right")

    def _slider(self, parent, key, title, decimals, steps, pad_bottom=6):
        lo, hi = LIMITS[key]
        value = self.engine.params[key]
        label = ctk.CTkLabel(parent, text=f"{title}: {value:.{decimals}f}", font=ctk.CTkFont(size=12))
        label.pack(anchor="w", padx=14, pady=(2, 0))

        def on_change(raw):
            v = round(float(raw), decimals)
            self.engine.params[key] = v
            label.configure(text=f"{title}: {v:.{decimals}f}")

        slider = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps, command=on_change)
        slider.set(value)
        slider.pack(fill="x", padx=14, pady=(0, pad_bottom))
        return label, slider

    # ----------------------------------------------------------- Rebinding callbacks
    def on_start_rebind(self, action_id):
        if self.current_rebind_id and self.current_rebind_id != action_id:
            self.on_rebind_cancel(self.current_rebind_id)

        self.current_rebind_id = action_id
        btn = self.key_buttons.get(action_id)
        if btn:
            btn.configure(text="Press key... (ESC)", fg_color="#D35400", hover_color="#BA4A00")

        self.engine.start_rebind(
            action_id,
            on_done=lambda aid, k: self.after(0, self.on_rebind_done, aid, k),
            on_cancel=lambda aid: self.after(0, self.on_rebind_cancel, aid)
        )

    def on_rebind_done(self, action_id, key_name):
        self.current_rebind_id = None
        btn = self.key_buttons.get(action_id)
        if btn:
            keys = self.engine.keybinds.get(action_id, [key_name])
            btn.configure(text=", ".join(keys), fg_color="#2D3748", hover_color="#4A5568")
        self.refresh_diagram_labels()
        self.show_key_status(f"Bound to {key_name}!")

    def on_rebind_cancel(self, action_id):
        self.current_rebind_id = None
        btn = self.key_buttons.get(action_id)
        if btn:
            keys = self.engine.keybinds.get(action_id, [])
            btn.configure(text=", ".join(keys), fg_color="#2D3748", hover_color="#4A5568")

    def on_reset_keybinds(self):
        if self.current_rebind_id:
            self.engine.cancel_rebind()
            self.current_rebind_id = None
        self.engine.reset_keybinds_to_default()
        for aid, btn in self.key_buttons.items():
            keys = self.engine.keybinds.get(aid, [])
            btn.configure(text=", ".join(keys), fg_color="#2D3748", hover_color="#4A5568")
        self.refresh_diagram_labels()
        self.show_key_status("Keybinds Reset to Defaults!")

    def show_key_status(self, text, color="#00E676"):
        self.key_save_status.configure(text=text, text_color=color)
        self.after(2500, lambda: self.key_save_status.configure(text=""))

    # ----------------------------------------------------------- mode callbacks
    def on_aim_only_toggle(self):
        self.engine.set_aim_only(self.aim_only_var.get())

    def on_topmost_toggle(self):
        self.engine.params["always_on_top"] = self.topmost_var.get()
        self.attributes("-topmost", self.topmost_var.get())

    def on_invert_y_toggle(self):
        self.engine.params["invert_y"] = self.invert_y_var.get()

    def on_block_mouse_toggle(self):
        self.engine.params["block_mouse_move"] = self.block_mouse_var.get()

    def on_booster_toggle(self):
        self.engine.params["rotational_booster"] = self.booster_var.get()

    def on_auto_test(self):
        if self.engine.auto_test_running:
            return

        def _run():
            for sec in (3, 2, 1):
                self.auto_test_btn.configure(
                    text=f"Starting in {sec}s... Focus Roblox now!",
                    fg_color="#D35400"
                )
                time.sleep(1.0)

            self.auto_test_btn.configure(
                text="TESTING CONTROLLER IN-GAME (4s)...",
                fg_color="#00E676",
                text_color="#000000"
            )

            def _done():
                self.auto_test_btn.configure(
                    text="3s Auto-Controller Test (Click, then focus Roblox)",
                    fg_color="#1F6AA5",
                    text_color="#FFFFFF"
                )

            self.engine.run_auto_test(on_done=_done)

        threading.Thread(target=_run, daemon=True).start()

    def on_save_settings(self):
        if self.engine.save_config():
            self.save_status.configure(text="Saved!")
            self.show_key_status("Saved to config.json!")
            self.after(2000, lambda: self.save_status.configure(text=""))
        else:
            self.save_status.configure(text="Save failed", text_color="#FF4B4B")
            self.show_key_status("Save failed", color="#FF4B4B")

    # ----------------------------------------------------------- telemetry
    def update_telemetry(self):
        if self._closing:
            return
        if self.engine.shutdown_requested.is_set():  # END key was pressed
            self.on_closing()
            return

        s = self.engine.snapshot()
        if s["active"]:
            self.status_frame.configure(fg_color="#102E1B", border_color="#00E676")
            self.status_label.configure(text="STATUS: ACTIVE (Physical KBM Suppressed)",
                                        text_color="#00E676")
        else:
            self.status_frame.configure(fg_color="#2E1414", border_color="#FF4B4B")
            self.status_label.configure(text="STATUS: PAUSED (Press F8)", text_color="#FF4B4B")

        slot = get_connected_xinput_slot()
        if slot == 0:
            self.slot_label.configure(
                text="XInput Slot: Player 1 (Slot 0 - Active for Roblox!)",
                text_color="#00E676"
            )
        elif slot is not None:
            self.slot_label.configure(
                text=f"XInput Slot: Player {slot+1} (Slot {slot}) - WARNING: Roblox prefers Slot 0!",
                text_color="#FF9800"
            )
        else:
            self.slot_label.configure(
                text="XInput Slot: Not Connected",
                text_color="#FF4B4B"
            )

        self.stick_label.configure(
            text=f"LS  X:{s['lx']:5.2f} Y:{s['ly']:5.2f}   |   RS  X:{s['rx']:5.2f} Y:{s['ry']:5.2f}")
        buttons = ", ".join(s["buttons"]) if s["buttons"] else "None"
        self.trigger_label.configure(
            text=f"LT:{s['lt']:.1f}  RT:{s['rt']:.1f}   |   Buttons: {buttons}")
        dx, dy = s["last_delta"]
        self.mouse_label.configure(
            text=f"Mouse events: {s['mouse_events']}   Last move: dx={dx} dy={dy}")

        # Live visual glow and deflection on the controller diagram
        self._update_diagram_glow(s)

        self.after(50, self.update_telemetry)

    def on_closing(self):
        if self._closing:
            return
        self._closing = True
        self.engine.stop()
        self.destroy()


def main():
    print("=" * 60)
    print("  KBM-to-XInput Virtual Controller: Phase 11 Active")
    print("  [F8] toggle Active/Paused    [END] emergency exit")
    print("=" * 60)

    try:
        engine = Engine(CONFIG_PATH)
    except Exception as exc:
        fatal(
            "Virtual controller could not start",
            f"{exc}\n\nMost common cause: the ViGEmBus driver is not installed "
            "(or the PC needs a restart after installing it).\n"
            "Install it from: https://github.com/nefarius/ViGEmBus/releases",
        )

    slot = get_connected_xinput_slot()
    if slot == 0:
        print("XInput Status: [CONNECTED ON SLOT 0 - Player 1] (Active for Roblox!)", flush=True)
    elif slot is not None:
        print(f"XInput Status: [CONNECTED ON SLOT {slot}] (Warning: Roblox prefers Slot 0)", flush=True)
    else:
        print("XInput Status: [NOT CONNECTED]", flush=True)

    app = ControllerApp(engine)
    try:
        app.mainloop()
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
