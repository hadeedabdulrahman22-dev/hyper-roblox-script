# KBM-to-XInput Virtual Controller

Turns your keyboard + mouse into a virtual Xbox controller (for Roblox shooters with controller aim assist). Windows only.

## First-time setup
1. Install Python 3.10+ (tick "Add Python to PATH").
2. Make sure the **ViGEmBus** driver is installed (https://github.com/nefarius/ViGEmBus/releases), then restart the PC.
3. Double-click `run_controller.bat`. First run installs everything automatically.

## Controls
- **F8**: toggle Active / Paused
- **END**: emergency exit (always works)

| Keyboard / Mouse | Controller |
|---|---|
| W A S D | Left stick |
| Mouse move | Right stick |
| Left click / Right click | RT / LT |
| Space | A (jump) |
| C / Shift | B (slide) |
| R | X (reload) |
| 1 / 2 / 3 | Y (swap weapon) |
| Q / E | LB / RB |
| X | D-pad up |
| F | R3 (melee) |

## Troubleshooting
- Window closes instantly: run `run_controller.bat` and read the text on screen.
- "Virtual controller could not start": ViGEmBus missing - install it and restart.
- Active but aim does nothing: check the yellow "Mouse events" line in the app. If it stays at 0 while you move the mouse, the hook is not seeing the mouse.
- Roblox/anti-cheat may flag virtual input drivers. Use at your own risk.
