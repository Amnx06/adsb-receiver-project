import numpy as np
import os


def load_iq_file(filepath):
    """
    Load a raw RTL-SDR .bin file and return centered complex IQ samples.

    Pipeline:
        raw uint8 (0–255)
        → float32
        → subtract 127.5   (center around zero)
        → split I / Q      (de-interleave)
        → complex64        (I + jQ)

    Args:
        filepath (str): path to the .bin file

    Returns:
        iq (np.ndarray): complex64 array of IQ samples
    """

    # Guard: check file exists
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"[LOADER] File not found: {filepath}")

    # Step 1 — Read raw bytes as uint8 (values 0 to 255)
    raw = np.fromfile(filepath, dtype=np.uint8)
    print(f'raw file: {raw}')

    # Step 2 — Convert to float32 so we can do math on it
    samples = raw.astype(np.float32)

    # Step 3 — Subtract 127.5 to center the signal around zero
    # RTL-SDR outputs unsigned values (0–255), midpoint is 127.5
    # All signal processing algorithms expect values centered at 0
    samples -= 127.5
    print(f'samples: {samples}')
    # Step 4 — Separate interleaved I and Q channels
    # RTL-SDR stores: [I0, Q0, I1, Q1, I2, Q2, ...]
    # Even indices → I (In-phase)
    # Odd  indices → Q (Quadrature)
    I = samples[0::2]
    Q = samples[1::2]

    # Step 5 — Combine into a single complex array (I + jQ)
    iq = (I + 1j * Q).astype(np.complex64)

    # Summary printout
    print(f"[LOADER] File        : {os.path.basename(filepath)}")
    print(f"[LOADER] Total bytes : {len(raw):,}")
    print(f"[LOADER] IQ samples  : {len(iq):,}")
    print(f"[LOADER] I range     : {I.min():.1f}  to  {I.max():.1f}")
    print(f"[LOADER] Q range     : {Q.min():.1f}  to  {Q.max():.1f}")
    print(f"[LOADER] dtype       : {iq.dtype}")

    return iq


if __name__ == "__main__":
    import sys

    # Use argument if given, otherwise fall back to default test file
    path = sys.argv[1] if len(sys.argv) > 1 else \
           "captures/simulated_20260329_151056.bin"

    iq = load_iq_file(path)

    print(f"\nFirst 5 complex samples:")
    for i, s in enumerate(iq[:5]):
        print(f"  sample[{i}] = {s.real:8.2f} + {s.imag:8.2f}j")

    # Self-validation checks
    print("\nRunning validation checks...")
    assert iq.dtype == np.complex64,    "FAIL — wrong dtype"
    assert iq.real.min() >= -127.5,     "FAIL — I values out of range"
    assert iq.real.max() <= 127.5,      "FAIL — I values out of range"
    assert iq.imag.min() >= -127.5,     "FAIL — Q values out of range"
    assert iq.imag.max() <= 127.5,      "FAIL — Q values out of range"
    print("All checks passed — file_loader.py is working correctly!")
