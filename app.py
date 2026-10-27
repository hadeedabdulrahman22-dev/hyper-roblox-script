"""KBM-to-XInput Virtual Controller - GUI. Run with run_controller.bat."""
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox


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
    from controller_core import CONFIG_PATH, LIMITS, Engine, get_connected_xinput_slot
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

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.title("KBM-to-XInput Virtual Controller")
        self.geometry("540x880")
        self.resizable(False, False)
        self.attributes("-topmost", engine.params["always_on_top"])
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.create_widgets()
        self.engine.start()
        self.update_telemetry()

    # ------------------------------------------------------------------ UI
    def create_widgets(self):
        p = self.engine.params

        # 1. Status banner
        self.status_frame = ctk.CTkFrame(self, corner_radius=12, border_width=2)
        self.status_frame.pack(fill="x", padx=16, pady=(14, 6))

        self.status_label = ctk.CTkLabel(
            self.status_frame, text="STATUS: PAUSED (Press F8)",
            font=ctk.CTkFont(size=18, weight="bold"))
        self.status_label.pack(pady=(10, 2))

        ctk.CTkLabel(
            self.status_frame,
            text="[F8] Toggle Active/Paused   |   [END] Emergency Kill-Switch",
            font=ctk.CTkFont(size=11), text_color="#A0A0A0").pack(pady=(0, 4))

        # XInput Slot Status Indicator
        self.slot_label = ctk.CTkLabel(
            self.status_frame,
            text="XInput Status: Checking...",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#00E676")
        self.slot_label.pack(pady=(0, 8))

        # 2. "3s Auto-Controller Test" Button (Bright & Prominent)
        self.auto_test_btn = ctk.CTkButton(
            self,
            text="3s Auto-Controller Test (Click, then focus Roblox)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1F6AA5",
            hover_color="#144870",
            height=38,
            command=self.on_auto_test
        )
        self.auto_test_btn.pack(fill="x", padx=16, pady=(4, 8))

        # 3. Mode controls
        mode = ctk.CTkFrame(self, corner_radius=10)
        mode.pack(fill="x", padx=16, pady=4)

        self.aim_only_var = ctk.BooleanVar(value=p["aim_only"])
        ctk.CTkSwitch(
            mode, text="Aim-Only Mode (Mouse -> Right Stick Only)",
            variable=self.aim_only_var, font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_aim_only_toggle).pack(anchor="w", padx=16, pady=(10, 2))
        ctk.CTkLabel(
            mode, text="Off = Full Controller Mode (keyboard + mouse both become controller)",
            font=ctk.CTkFont(size=10), text_color="#888888").pack(anchor="w", padx=16, pady=(0, 6))

        row1 = ctk.CTkFrame(mode, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(0, 4))
        self.topmost_var = ctk.BooleanVar(value=p["always_on_top"])
        ctk.CTkCheckBox(row1, text="Always on Top", variable=self.topmost_var,
                        command=self.on_topmost_toggle).pack(side="left", padx=(0, 20))
        self.invert_y_var = ctk.BooleanVar(value=p["invert_y"])
        ctk.CTkCheckBox(row1, text="Invert Y-Axis", variable=self.invert_y_var,
                        command=self.on_invert_y_toggle).pack(side="left")

        # Row 2 Checkbox: Block Physical Mouse Move
        self.block_mouse_var = ctk.BooleanVar(value=p["block_mouse_move"])
        ctk.CTkCheckBox(
            mode,
            text="Block Physical Mouse Move (Unchecked = Smooth Cursor Centering)",
            variable=self.block_mouse_var,
            command=self.on_block_mouse_toggle
        ).pack(anchor="w", padx=16, pady=(4, 10))

        # 4. Sliders
        sliders = ctk.CTkFrame(self, corner_radius=10)
        sliders.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(sliders, text="Mouse Aim & Curve Tuning",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(8, 6))

        self.sens_label, self.sens_slider = self._slider(
            sliders, "sensitivity", "Sensitivity", 3, 145)
        self.dz_label, self.dz_slider = self._slider(
            sliders, "anti_deadzone", "Anti-Deadzone Boost", 2, 35)
        self.expo_label, self.expo_slider = self._slider(
            sliders, "exponent", "Response Exponent", 2, 110)
        self.smooth_label, self.smooth_slider = self._slider(
            sliders, "smoothing", "Smoothing (Anti-Jitter)", 2, 85, pad_bottom=10)

        # 5. Telemetry
        telem = ctk.CTkFrame(self, corner_radius=10)
        telem.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(telem, text="Live Virtual Controller Telemetry",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=14, pady=(6, 2))
        mono = ctk.CTkFont(family="Consolas", size=11)
        self.stick_label = ctk.CTkLabel(telem, text="", font=mono)
        self.stick_label.pack(anchor="w", padx=14, pady=2)
        self.trigger_label = ctk.CTkLabel(telem, text="", font=mono, text_color="#88C0D0")
        self.trigger_label.pack(anchor="w", padx=14, pady=2)
        self.mouse_label = ctk.CTkLabel(telem, text="", font=mono, text_color="#EBCB8B")
        self.mouse_label.pack(anchor="w", padx=14, pady=(2, 8))

        # 6. Save
        action = ctk.CTkFrame(self, fg_color="transparent")
        action.pack(fill="x", padx=16, pady=(6, 10))
        ctk.CTkButton(action, text="Save Settings (config.json)",
                      font=ctk.CTkFont(size=13, weight="bold"), height=36,
                      command=self.on_save_settings).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.save_status = ctk.CTkLabel(action, text="", text_color="#00E676",
                                        font=ctk.CTkFont(size=12, weight="bold"))
        self.save_status.pack(side="right")

    def _slider(self, parent, key, title, decimals, steps, pad_bottom=6):
        lo, hi = LIMITS[key]
        value = self.engine.params[key]
        label = ctk.CTkLabel(parent, text=f"{title}: {value:.{decimals}f}", font=ctk.CTkFont(size=12))
        label.pack(anchor="w", padx=16, pady=(2, 0))

        def on_change(raw):
            v = round(float(raw), decimals)
            self.engine.params[key] = v
            label.configure(text=f"{title}: {v:.{decimals}f}")

        slider = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps, command=on_change)
        slider.set(value)
        slider.pack(fill="x", padx=16, pady=(0, pad_bottom))
        return label, slider

    # ----------------------------------------------------------- callbacks
    def on_aim_only_toggle(self):
        self.engine.set_aim_only(self.aim_only_var.get())

    def on_topmost_toggle(self):
        self.engine.params["always_on_top"] = self.topmost_var.get()
        self.attributes("-topmost", self.topmost_var.get())

    def on_invert_y_toggle(self):
        self.engine.params["invert_y"] = self.invert_y_var.get()

    def on_block_mouse_toggle(self):
        self.engine.params["block_mouse_move"] = self.block_mouse_var.get()

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
            self.after(2000, lambda: self.save_status.configure(text=""))
        else:
            self.save_status.configure(text="Save failed", text_color="#FF4B4B")

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

        self.after(50, self.update_telemetry)

    def on_closing(self):
        if self._closing:
            return
        self._closing = True
        self.engine.stop()
        self.destroy()


def main():
    print("=" * 60)
    print("  KBM-to-XInput Virtual Controller: Phase 7 GUI Active")
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
