import numpy as np

PREAMBLE_CHIPS = [1,0,1,0,0,0,0,1,0,1,0,0,0,0,0,0]
FS = 2e6          # 2 MSps
SPS = 2           # samples per chip at 2 MSps

def generate_sample(snr_db, label, freq_offset_hz=0, multipath=False):
    """
    Returns: (window, label)
      window : numpy array shape (256,) — magnitude IQ samples
      label  : 1 = preamble present, 0 = noise only
    """
    N = 256
    signal = np.zeros(N, dtype=complex)

    if label == 1:
        # Build preamble burst at samples 0–31 (16 chips × 2 sps)
        for i, chip in enumerate(PREAMBLE_CHIPS):
            if chip == 1:
                signal[i*SPS : i*SPS+SPS] = 1.0

        # Apply frequency offset: multiply by complex exponential
        if freq_offset_hz != 0:
            t = np.arange(N) / FS
            signal *= np.exp(1j * 2 * np.pi * freq_offset_hz * t)

        # Two-tap multipath: add delayed attenuated copy
        if multipath:
            delay = 4   # 4 samples = 2 µs delay
            att   = 0.4 # 40% amplitude of second path
            delayed = np.roll(signal, delay) * att
            signal += delayed

    # Add AWGN
    snr_lin   = 10 ** (snr_db / 20)
    noise_std = 1.0 / snr_lin
    noise     = (np.random.randn(N) + 1j*np.random.randn(N)) * noise_std / np.sqrt(2)
    received  = signal + noise

    # Return magnitude envelope (same as your existing pipeline)
    magnitude = np.abs(received).astype(np.float32)
    return magnitude, label


def build_dataset(snr_levels, n_per_class_per_snr=1000):
    """
    Returns X shape (total_samples, 256), y shape (total_samples,)
    """
    X, y = [], []
    for snr in snr_levels:
        for _ in range(n_per_class_per_snr):
            x1, l1 = generate_sample(snr, label=1)
            x0, l0 = generate_sample(snr, label=0)
            X.append(x1); y.append(l1)
            X.append(x0); y.append(l0)
    return np.array(X), np.array(y)
snrr= [15,16,17,18,19]
a,b =build_dataset(snrr)
print(f"\n a = {len(a)}")
print(f"\n b = {b}")