from pathlib import Path
import math
import os
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, TextBox
import pyModeS as pms


def prompt_user_parameters() -> tuple[int, int, int]:
    """Ask the user for the number of samples and the slice.

    Returns:
        tuple: (num_iq_bytes, slice_index, scaler)
    """
    print("=====================>>>>>>>><<<<<<<==================")
    print("\nWelcome to ADS-B Visualizer >>>")
    print("\nPress 0 to exit")

    while True:
        raw_samples = input("Enter the number of samples in plot : 20,100,2000 : ")
        if raw_samples.strip() == "0":
            return 0, 0, 0

        try:
            nsamples = int(raw_samples) * 2
            break
        except ValueError:
            print("Please enter a valid integer sample count.")

    while True:
        raw_slice = input("Select the slice you want to visualize by entering the X multiple integer of the sample window: ")
        try:
            slice_index = int(raw_slice)
            break
        except ValueError:
            print("Please enter a valid integer slice number.")

    if nsamples <= 50:
        scaler = 1
    elif nsamples < 200:
        scaler = 2
    elif nsamples < 1000:
        scaler = 50
    else:
        scaler = 100

    return nsamples, slice_index, scaler


def load_iq_samples(binary_file: str, num_bytes: int, slice_index: int) -> tuple[list[float], list[float]]:
    """Load IQ bytes from the capture file and convert to I/Q sample pairs.

    Args:
        binary_file: path to the raw binary capture.
        num_bytes: number of raw bytes to read.
        slice_index: the slice to display.

    Returns:
        tuple: I and Q sample lists.
    """
    '''if not os.path.exists(binary_file):
        raise FileNotFoundError(f"Binary file not found: {binary_file}")
'''
    start_byte = num_bytes * (slice_index - 1)
    a = "C:/Users/ucef-/Desktop/adsb-receiver-project/captures/capture_Stah1090MHZ.bin"
    with open(a, "rb") as f:
        f.seek(start_byte)
        chunk = f.read(num_bytes)

    if len(chunk) < num_bytes:
        raise ValueError("Not enough data in the capture file for the requested slice.")

    i_samples: list[float] = []
    q_samples: list[float] = []

    for idx, raw_value in enumerate(chunk):
        normalized = raw_value - 127.5
        if idx % 2 == 0:
            i_samples.append(normalized)
        else:
            q_samples.append(normalized)

    return i_samples, q_samples


def compute_magnitudes(i_samples: list[float], q_samples: list[float], dc_shift: float = 0.7) -> list[float]:
    """Compute the magnitude of each IQ sample pair."""
    magnitudes: list[float] = []
    for i, q in zip(i_samples, q_samples):
        mag = math.sqrt(i * i + q * q) - dc_shift
        magnitudes.append(round(mag, 2))
    return magnitudes


def build_preamble_template() -> np.ndarray:
    """Build the ADS-B preamble pulse pattern used for correlation."""
    preamble = np.zeros(26, dtype=float)
    pulse_positions = [0, 2, 7, 9, 16, 19, 21, 23, 24]
    preamble[pulse_positions] = 1.0
    return preamble


def detect_preamble_candidates(signal: list[float], preamble: np.ndarray, threshold: float = 8.0) -> tuple[dict[int, float], np.ndarray]:
    """Detect candidate preamble locations using thresholded correlation."""
    correlation_values = np.correlate(signal, preamble, mode="valid")
    candidates: dict[int, float] = {}

    for idx in range(20, len(correlation_values)):
        valley_avg = 0.2 * (
            correlation_values[idx - 6]
            + correlation_values[idx - 11]
            + correlation_values[idx - 13]
            + correlation_values[idx - 18]
            + correlation_values[idx - 20]
        )
        if valley_avg == 0:
            continue

        static_ratio = correlation_values[idx] / valley_avg
        
        if static_ratio > threshold:
            if candidates:
                last_index = list(candidates)[-1]
                if idx - last_index < 240 :
                    if static_ratio > list(candidates.values())[-1]:
                        
                        candidates.popitem()
                        candidates[idx] = static_ratio
                else:
                        candidates[idx] = static_ratio
            else:
                    candidates[idx] = static_ratio

    return candidates, correlation_values


def PPM_Demodulation(values: list[float]) -> str:
    """Demodulate a list of magnitudes into a binary string based on pulse positions."""
    if len(values) % 2 != 0:
        return ""

    bits: list[str] = []
    for j in range(0, len(values), 2):
        first = values[j]
        second = values[j + 1]
        bits.append("1" if first >= second else "0")
    return "".join(bits)


def apply_symbol_match(magnitude: list[float], candidates: dict[int, float]) -> dict[int, str]:
    """Apply criterion 2 by checking known pulse symbol pattern."""
    reference_bits = "110010001"
    good_indices: dict[int, str] = {}

    for index in candidates:
        window = magnitude[index : index + 26]
        if len(window) < 26:
            continue

        extracted = window[0:4] + window[6:10] + window[-10:]
        bits = PPM_Demodulation(extracted)
        if bits == reference_bits:
            good_indices[index] = bits

    return good_indices


def apply_power_ratio_test(magnitude: list[float], indices: list[int], threshold: float = 6.656) -> dict[int, float]:
    """Apply criterion 3 to reject inconsistent preamble power.

    Returns indices that pass the power consistency check.
    """
    good_indices: dict[int, float] = {}
    for index in indices:
        window = magnitude[index : index + 26]
        if len(window) < 26:
            continue

        pulses = [window[pos] for pos in [0, 2, 7, 9, 16, 19, 21, 23, 24]]
        min_pulse = min(pulses)
        if min_pulse == 0:
            continue

        power_ratio = max(pulses) / min_pulse
        if power_ratio < threshold:
            good_indices[index] = power_ratio

    return good_indices


def apply_empty_slot_test(magnitude: list[float], indices: list[int]) -> dict[int, int]:
    """Apply criterion 4 by verifying empty symbol regions."""
    good_indices: dict[int, int] = {}
    for index in indices:
        window = magnitude[index : index + 26]
        if len(window) < 26:
            continue

        pulse_positions = [0, 2, 7, 9, 16, 19, 21, 23, 24]
        pulses = [window[pos] for pos in pulse_positions]
        sigma = sum(pulses) / len(pulses)

        test_positions = [4, 5, 10, 11, 12, 13, 14, 15]
        empty_count = 0
        for pos in range(0, len(test_positions), 2):
            left = window[test_positions[pos]]
            right = window[test_positions[pos + 1]]
            if max(left, right) <= sigma / 2:
                empty_count += 1

        if empty_count >= 2:
            good_indices[index] = empty_count

    return good_indices


def build_raw_messages(magnitude: list[float], indices: list[int]) -> dict[int, str]:
    """Build raw binary strings for candidate ADS-B messages."""
    messages: dict[int, str] = {}
    for index in indices:
        raw_frame = magnitude[index + 16 : index + 240]
        if len(raw_frame) < 224:
            continue
        messages[index] = PPM_Demodulation(raw_frame)
    return messages


def decode_messages(messages: dict[int, str]) -> None:
    """Decode and print ADS-B messages using pyModeS."""
    for index, binary_string in messages.items():
        print("\n" + "=" * 50)
        print(f"REPORT FOR INDEX: {index}")
        try:
            hex_msg = pms.util.bin2hex(binary_string)
            decoded = pms.decode(hex_msg)
            valid_crc = decoded.get("crc_valid", False)
            tc = decoded.get("typecode")
            icao = decoded.get("icao")

            print(f"Hex Message:  {hex_msg}")
            print(f"CRC Result:   {'Valid' if valid_crc else 'Corrupted'}")
            print(f"ICAO Address: {icao}")
            print(f"Typecode:     {tc}")
            print("-" * 50)

            if not valid_crc or tc is None:
                print("Skipping detailed parse (Invalid CRC or Unknown Typecode).")
                continue

            if 1 <= tc <= 4:
                print("[IDENTIFICATION]")
                print(f"Callsign: {decoded.get('callsign', 'N/A')}")
            elif 5 <= tc <= 8:
                print("[SURFACE POSITION]")
                print_position(decoded, binary_string)
            elif 9 <= tc <= 18:
                print("[AIRBORNE POSITION]")
                print(f"Altitude:  {decoded.get('altitude', 'N/A')} ft")
                print_position(decoded, binary_string)
            elif tc == 19:
                print("[AIRBORNE VELOCITY]")
                print_velocity(decoded)
            elif tc == 31:
                print("[OPERATIONAL STATUS]")
                print(f"Capability: {decoded.get('capability', 'N/A')}")
        except Exception as exc:
            print(f"Detailed Error at index {index}: {exc}")


def print_position(decoded: dict, binary_string: str) -> None:
    """Print position fields or raw CPR values when global coords are missing."""
    lat = decoded.get("latitude")
    lon = decoded.get("longitude")
    if lat is not None and lon is not None:
        print(f"Global Latitude:  {lat}")
        print(f"Global Longitude: {lon}")
    elif len(binary_string) >= 88:
        raw_lat = int(binary_string[54:71], 2)
        raw_lon = int(binary_string[71:88], 2)
        print(f"Raw CPR Lat: {raw_lat} (Need reference to decode Global Lat)")
        print(f"Raw CPR Lon: {raw_lon} (Need reference to decode Global Lon)")

    cpr = decoded.get("cpr_format")
    if cpr is None and len(binary_string) >= 54:
        cpr = int(binary_string[53])
    print(f"CPR Type: {'Odd' if cpr == 1 else 'Even'}")


def print_velocity(decoded: dict) -> None:
    """Print velocity fields with unit conversions."""
    gs = decoded.get("groundspeed")
    if gs is not None:
        gs_kmh = round(gs * 1.852, 2)
        print(f"Ground Speed: {gs} knots ({gs_kmh} km/h)")
        print(f"Track Angle:  {decoded.get('track')}°")

    airspeed = decoded.get("airspeed")
    if airspeed is not None:
        as_kmh = round(airspeed * 1.852, 2)
        print(f"Air Speed:    {airspeed} knots ({as_kmh} km/h)")
        print(f"Heading:      {decoded.get('heading')}°")

    vrate_fpm = decoded.get("vertical_rate")
    if vrate_fpm is not None:
        vrate_km_min = round((vrate_fpm * 0.3048) / 1000, 4)
        vrate_ms = round((vrate_fpm * 0.3048) / 60, 2)
        status = "Climbing" if vrate_fpm > 0 else "Descending"
        print(f"Vertical Rate: {vrate_fpm} fpm ({status})")
        print(f"            -> {abs(vrate_km_min)} km/min")
        print(f"            -> {abs(vrate_ms)} m/s")


def compute_snr(magnitude: list[float], candidate_indices: list[int]) -> None:
    """Estimate SNR for each final candidate index."""
    for index in candidate_indices:
        if index < 225 or index + 224 > len(magnitude):
            continue

        signal_power = sum(magnitude[index : index + 224]) ** 2 / 224
        noise_power = sum(magnitude[index - 225 : index - 1]) ** 2 / 224
        if noise_power <= 0:
            continue

        snr_db = 10 * math.log10(signal_power / noise_power)
        print(f"\nSNR at index {index}: {snr_db:.2f} dB")


def plot_signal(magnitude: list[float], correlation_values: np.ndarray, start_byte: int, scaler: int) -> None:
    """Plot the signal magnitude and correlation values."""
    if not magnitude:
        return

    class SignalShifter:
        def __init__(self, stem_container, base_xx, base_yy):
            self.shift_amount = 0
            self.stem_container = stem_container
            self.base_xx = base_xx
            self.base_yy = base_yy

        def update_position(self):
            new_xx = self.base_xx + self.shift_amount
            self.stem_container.markerline.set_xdata(new_xx)
            new_segments = [[[x, 0], [x, y]] for x, y in zip(new_xx, self.base_yy)]
            self.stem_container.stemlines.set_segments(new_segments)
            plt.draw()

        def shift_by_button(self, event):
            self.shift_amount += 1
            self.update_position()

        def shift_by_text(self, text):
            try:
                self.shift_amount = int(text)
                self.update_position()
            except ValueError:
                print("Please enter an integer.")

    sample_count = len(magnitude)
    x = np.arange(sample_count)
    y = np.array(magnitude)

    preamble_x = np.arange(26)
    preamble_y = np.zeros(26)
    preamble_y[[0, 2, 7, 9, 16, 19, 21, 23, 24]] = 3

    fig = plt.figure(figsize=(6, 4))
    ax = fig.add_axes([0.07, 0.1, 1, 1])
    ax.plot(x, y, label="Signal")
    stem_container = ax.stem(preamble_x, preamble_y, linefmt="red", label="Preamble pulses")
    ax.set_xlabel(f"IQ SAMPLES (0.5 µs per sample), start byte: {start_byte}")
    ax.set_ylabel("Magnitude")
    ax.set_xlim(0, sample_count)
    ax.set_ylim(0, max(y) + 1)
    ax.set_xticks(scaler * np.arange(1, max(2, sample_count // scaler)))
    ax.grid(True)

    callback = SignalShifter(stem_container, preamble_x, preamble_y)
    button_ax = plt.axes([0.04, 0.005, 0.1, 0.04])
    btn = Button(button_ax, "Shift", color="lightgray", hovercolor="white")
    btn.on_clicked(callback.shift_by_button)

    textbox_ax = plt.axes([0.87, 0.005, 0.1, 0.04])
    textbox = TextBox(textbox_ax, "jump to:", initial="0")
    textbox.on_submit(callback.shift_by_text)

    corr_fig = plt.figure(figsize=(6, 4))
    corr_ax = corr_fig.add_axes([0.07, 0.1, 1, 1])
    corr_ax.plot(np.arange(len(correlation_values)), correlation_values, color="red")
    corr_ax.set_xlim(0, len(correlation_values))
    corr_ax.set_ylim(0, max(correlation_values) + 10)
    corr_ax.grid(True)

    plt.show()


def main() -> None:
    binary_file = os.path.join(os.path.dirname(__file__), "captures", "capture_Stah1090MHZ.bin")

    while True:
        nsamples, slice_index, scaler = prompt_user_parameters()
        if slice_index == 0:
            break

        i_samples, q_samples = load_iq_samples(binary_file, nsamples, slice_index)
        magnitudes = compute_magnitudes(i_samples, q_samples)
        preamble = build_preamble_template()
        signal = magnitudes[: nsamples // 2]

        candidates, correlation_values = detect_preamble_candidates(signal, preamble)
        matched_candidates = apply_symbol_match(magnitudes, candidates)
        power_candidates = apply_power_ratio_test(magnitudes, list(matched_candidates.keys()))
        final_candidates = apply_empty_slot_test(magnitudes, list(power_candidates.keys()))

        print(f"\nCriterion 1: {len(candidates)} candidates -> {list(candidates.keys())}")
        print(f"Criterion 2: {len(matched_candidates)} matches -> {list(matched_candidates.keys())}")
        print(f"Criterion 3: {len(power_candidates)} power-consistent -> {list(power_candidates.keys())}")
        print(f"Criterion 4: {len(final_candidates)} final candidates -> {list(final_candidates.keys())}")

        raw_messages = build_raw_messages(magnitudes, list(final_candidates.keys()))
        decode_messages(raw_messages)
        compute_snr(magnitudes, list(final_candidates.keys()))

        if nsamples <= 2000:
            plot_signal(magnitudes, correlation_values, nsamples * (slice_index - 1), scaler)
        else:
            print("\nReduce the number of samples to lower than 2000 to visualize.")


if __name__ == "__main__":
    main()

'''Path('SignalVisualizer.py').write_text(content, encoding='utf-8')
PY'''