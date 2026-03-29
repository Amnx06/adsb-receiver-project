import numpy as np
import os
from datetime import datetime


def generate_fake_adsb_capture(duration_seconds=0.01,
                                sample_rate=2_000_000,
                                output_dir="captures"):
    """
    Generates a .bin file that mimics real RTL-SDR output.
    Format: uint8, interleaved I/Q, centered around 127.5
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"simulated_{timestamp}.bin")

    n_samples = sample_rate * duration_seconds

    # Noise floor
    noise_I = np.random.normal(0, 10, n_samples).astype(np.float32)
    noise_Q = np.random.normal(0, 10, n_samples).astype(np.float32)

    # Simulated carrier tone at 100 kHz offset
    t = np.arange(n_samples) / sample_rate
    freq_offset = 100_000
    tone_I = 40 * np.cos(2 * np.pi * freq_offset * t).astype(np.float32)
    tone_Q = 40 * np.sin(2 * np.pi * freq_offset * t).astype(np.float32)

    # Combine and shift to uint8 range
    I = np.clip(noise_I + tone_I + 127.5, 0, 255).astype(np.uint8)
    Q = np.clip(noise_Q + tone_Q + 127.5, 0, 255).astype(np.uint8)

    # Interleave: [I0, Q0, I1, Q1, ...]
    interleaved = np.empty(2 * n_samples, dtype=np.uint8)
    interleaved[0::2] = I
    interleaved[1::2] = Q

    interleaved.tofile(output_file)
    print(f"[SIM] Generated {n_samples:,} samples → {output_file}")
    print(f"[SIM] File size: {os.path.getsize(output_file) / 1e6:.1f} MB")
    return output_file


if __name__ == "__main__":
    generate_fake_adsb_capture(duration_seconds=5)
