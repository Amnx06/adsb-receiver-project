import subprocess
import os
from datetime import datetime

# ── DEV MODE: set to False when real RTL-SDR is connected ──
USE_SIMULATOR = True
# ───────────────────────────────────────────────────────────

def capture_adsb(duration_seconds=0.01, output_dir="captures"):
    """
    Capture raw IQ samples from RTL-SDR for N seconds.
    In dev mode, calls the simulator instead of real hardware.
    """
    if USE_SIMULATOR:
        from simulator import generate_fake_adsb_capture
        print("[DEV MODE] No hardware — using simulator")
        return generate_fake_adsb_capture(duration_seconds, output_dir=output_dir)

    # --- Real hardware path ---
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"capture_{timestamp}.bin")
    n_samples = 2_000_000 * duration_seconds

    cmd = [
        "rtl_sdr",
        "-f", "1090000000",   # 1090 MHz — ADS-B frequency
        "-s", "2000000",      # 2 Msps sample rate
        "-n", str(n_samples),
        output_file
    ]

    print(f"[INFO] Capturing {duration_seconds}s → {output_file}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"[OK] Saved: {output_file}")
        return output_file
    else:
        print(f"[ERROR] rtl_sdr failed:\n{result.stderr}")
        return None


if __name__ == "__main__":
    capture_adsb(duration_seconds=5)
