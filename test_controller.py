import time
import urllib.request
import shutil
import os
import sys

def provide_vigembus_installer():
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    dest_msi = os.path.join(workspace_dir, "ViGEmBus_Setup_x64.msi")

    if os.path.exists(dest_msi):
        print(f"\nViGEmBus installer is already present at:\n  {dest_msi}")
        return dest_msi

    # Option A: Copy from vgamepad's internal package if present
    bundled_msi = os.path.join(
        workspace_dir,
        ".venv",
        "Lib",
        "site-packages",
        "vgamepad",
        "win",
        "vigem",
        "install",
        "x64",
        "ViGEmBusSetup_x64.msi"
    )

    if os.path.exists(bundled_msi):
        print(f"\nExtracting bundled ViGEmBus installer to:\n  {dest_msi}")
        shutil.copyfile(bundled_msi, dest_msi)
        print("Extracted successfully!")
        return dest_msi

    # Option B: Download official MSI from GitHub
    url = "https://github.com/nefarius/ViGEmBus/releases/download/setup-v1.17.333/ViGEmBusSetup_x64.msi"
    print(f"\nDownloading official ViGEmBus installer from GitHub to:\n  {dest_msi} ...")
    try:
        # Add User-Agent header for GitHub releases
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp, open(dest_msi, 'wb') as out_f:
            shutil.copyfileobj(resp, out_f)
        print(f"Downloaded successfully: {dest_msi}")
        return dest_msi
    except Exception as e:
        print(f"Failed to automatically download ViGEmBus installer: {e}")
        print("You can manually download the installer here:")
        print("https://github.com/nefarius/ViGEmBus/releases/latest")
        return None

def test_controller():
    print("Testing Virtual Xbox 360 Controller...")

    # Step 1: Initialize VX360Gamepad
    try:
        import vgamepad as vg
        gamepad = vg.VX360Gamepad()
    except Exception as e:
        print("\n" + "="*65)
        print("NOTICE: ViGEmBus driver is not installed on this PC.")
        print(f"Underlying error: {e}")
        print("="*65)
        print("A virtual controller needs the ViGEmBus driver to create virtual XInput devices.")
        installer_path = provide_vigembus_installer()
        print("="*65)
        if installer_path and os.path.exists(installer_path):
            print("NEXT STEP FOR YOU:")
            print(f"1. Double-click and run: {installer_path}")
            print("2. Complete the short installation wizard.")
            print("3. Run this script again: python test_controller.py")
        else:
            print("Please install ViGEmBus from https://github.com/nefarius/ViGEmBus/releases/latest")
        print("="*65 + "\n")
        sys.exit(1)

    # Step 2: Simulate pressing and releasing button 'A'
    try:
        print("Virtual Xbox 360 Gamepad initialized.")
        print("Pressing button 'A' for 1 second...")
        gamepad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        gamepad.update()

        time.sleep(1.0)

        gamepad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        gamepad.update()
        print("Button 'A' released.")

        print("\nSUCCESS: Virtual Xbox 360 Controller is working!\n")
    except Exception as e:
        print(f"Error during controller simulation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_controller()
