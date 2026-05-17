import math
import matplotlib.pyplot as plt
import numpy as np
import time
from matplotlib.widgets import Button, TextBox
import threading
import json
import pyModeS as pms
from pyModeS.util import bin2hex, crc
import os

# A script to visualize the sample(or time) versus magnitude signal from SDR tuned to 1090 MHz
# WITH SDR Sampling Frequency set to 2 Million Samples Per Second
# Chunked streaming version: processes 120 MB file in 100k-sample chunks
# Results are written to JSON immediately when a preamble is confirmed

# ── Global results store (written live to disk on every confirmed detection) ──
RESULTS_FILE = "output/results.json"
os.makedirs("output", exist_ok=True)

if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE, "r") as _f:
        all_results = json.load(_f)
else:
    all_results = {
        "capture_file": "",
        "sample_rate_msps": 2,
        "detections": [],
        "total_c1": 0,
        "total_c2": 0,
        "total_c3": 0,
        "total_final": 0
    }

# ── Preamble template (26-element characteristic word) ───────────────────────
preamble    = np.zeros(26)
PeaksIndex  = [0, 2, 7, 9, 16, 19, 21, 23, 24]   # α-positions
for _p in PeaksIndex:
    preamble[_p] = 1

# ── Bit slicer (unchanged from your original) ────────────────────────────────
def Bit_Slicer(message, Msg_length=224):
    for key, value in message.items():
        decoded = []
        for k in range(0, Msg_length, 2):
            if value[k] >= value[k + 1]:
                decoded.append(1)
            elif value[k] < value[k + 1]:
                decoded.append(0)
            else:
                decoded[:] = "Rejected"
                break
        message[key] = "".join(map(str, decoded))

# ── SNR calculation (unchanged from your original) ───────────────────────────
def SNR_Calculation(index, signal):
    l = signal[index: index + 224]
    p = signal[max(0, index - 225): index - 1]
    x = (sum(l)) * (sum(l)) / 224          # signal power estimate
    w = (sum(p)) * (sum(p)) / 224          # noise power estimate
    if w <= 0:
        return 0.0
    return round(10 * math.log10(x / w), 2)

# ── Write one confirmed detection to JSON immediately ─────────────────────────
def save_detection(local_idx, global_byte, c1_ratio, c3_ratio,
                   c4_count, signal):
    snr = SNR_Calculation(local_idx, signal)

    detection = {
        "global_byte_offset": global_byte,
        "c1_ratio":           round(c1_ratio, 3),
        "c2_match":           True,
        "c3_power_ratio":     round(c3_ratio, 3),
        "c4_null_count":      c4_count,
        "snr_db":             snr,
        "final_decision":     True
    }

    all_results["detections"].append(detection)
    all_results["total_final"] += 1

    with open(RESULTS_FILE, "w") as _f:
        json.dump(all_results, _f, indent=2)

    print(f"\n✓  PREAMBLE CONFIRMED"
          f"  global_byte={global_byte:,}"
          f"  SNR={snr:.1f} dB"
          f"  C1={c1_ratio:.1f}"
          f"  C3={c3_ratio:.2f}"
          f"  C4_nulls={c4_count}")

# ── Process one chunk: run all 4 criteria, write JSON on each confirmation ───
def process_chunk(signal, byte_offset, overlap_len,
                  total_c1, total_c2, total_c3, total_c4):
    """
    signal      : list of magnitude floats  =  overlap_buffer + chunk_mag
                  signal[0]  is NOT the start of the current chunk —
                  the first overlap_len samples belong to the END of the
                  previous chunk (already counted in byte_offset).

    byte_offset : file byte position of the FIRST byte of chunk_mag
                  (i.e. the position AFTER the previous chunk, NOT
                  counting the overlap).

    overlap_len : number of samples prepended from the previous chunk.

    Global sample index of signal[i]:
        global_sample = (byte_offset // 2) - overlap_len + i
    Global byte offset of signal[i]:
        global_byte   = global_sample * 2

    total_c1/2/3/4 : running counters, returned updated
    """

    # ── CRITERION 1: CFAR correlation ────────────────────────────────────────
    CorrelationValues = np.correlate(signal, preamble, mode="valid")

    Threshold        = 8
    ExceedThreshold  = {}           # { local_index : c1_ratio }

    for maximum in range(20, len(CorrelationValues)):
        valleyAvg = 0.2 * (
            CorrelationValues[maximum - 6]  +
            CorrelationValues[maximum - 11] +
            CorrelationValues[maximum - 13] +
            CorrelationValues[maximum - 18] +
            CorrelationValues[maximum - 20]
        )
        if valleyAvg < 0.001:       # avoid division by zero / very small noise
            continue

        PeakValue    = CorrelationValues[maximum]
        Static_Ratio = PeakValue / valleyAvg

        if Static_Ratio > Threshold:
            if ExceedThreshold:
                last_key = list(ExceedThreshold)[-1]
                if maximum - last_key < 240:
                    # Re-triggering: keep only the stronger peak
                    if Static_Ratio > list(ExceedThreshold.values())[-1]:
                        ExceedThreshold.popitem()
                        ExceedThreshold[maximum] = Static_Ratio
                else:
                    ExceedThreshold[maximum] = Static_Ratio
            else:
                ExceedThreshold[maximum] = Static_Ratio

    total_c1 += len(ExceedThreshold)
    #print(f"  C1: {len(ExceedThreshold)} candidates at indices "
    #      f"{list(ExceedThreshold.keys())}")

    # ── CRITERIA 2 / 3 / 4: tested immediately for each C1 candidate ─────────
    ref = "110010001"     # deterministic symbol pattern for DF=17

    for local_idx, c1_ratio in ExceedThreshold.items():

        # bounds check: need at least 26 samples ahead
        if local_idx + 26 > len(signal):
            continue

        # ── CRITERION 2: Deterministic Symbol Match ───────────────────────
        window = signal[local_idx: local_idx + 26]

        # 18 samples covering the 9 symbol pairs
        samples_18 = window[0:4] + window[6:10] + window[16:]  # same as your original

        temp = {local_idx: samples_18}
        Bit_Slicer(temp, Msg_length=18)

        if temp[local_idx] != ref:
            continue                # C2 failed → discard immediately

        total_c2 += 1
      #  print(f"    C2 passed at local_idx={local_idx}")

        # ── CRITERION 3: Consistent Power Test ───────────────────────────
        # Use the CORRECT α-positions from the paper
        peaks_9 = [
            window[0],  window[2],  window[7],  window[9],
            window[16], window[19], window[21], window[23], window[24]
        ]

        peak_min = min(peaks_9)
        if peak_min <= 0:
            continue                # avoid division by zero

        c3_ratio  = max(peaks_9) / peak_min
        Threshold3 = 5.656

        if c3_ratio >= Threshold3:
            continue                # C3 failed → discard immediately

        total_c3 += 1
       # print(f"    C3 passed at local_idx={local_idx}  power_ratio={c3_ratio:.2f}")

        # ── CRITERION 4: Null Symbol Validation ──────────────────────────
        sigma = sum(peaks_9) / 9    # dynamic threshold = mean of 9 peaks

        # β-positions: the 4 null symbol intervals (2 samples each)
        null_pairs = [
            (window[4],  window[5]),
            (window[10], window[11]),
            (window[12], window[13]),
            (window[14], window[15])
        ]

        empty_count = 0
        for s1, s2 in null_pairs:
            if s1 <= sigma / 2 and s2 <= sigma / 2:
                empty_count += 1

        if empty_count < 2:
            continue                # C4 failed → discard immediately

        # ── ALL 4 CRITERIA PASSED ─────────────────────────────────────────
        total_c4 += 1

        # ── Correct global byte address ───────────────────────────────────
        # signal = buffer + chunk_mag
        # signal[0] is the first overlap sample, which already appeared
        # at the END of the previous chunk. Its file byte position is:
#            (byte_offset - overlap_len * 2)
        # Therefore signal[local_idx] is at:
#            global_sample = (byte_offset // 2) - overlap_len + local_idx
#            global_byte   = global_sample * 2
        global_sample = (byte_offset // 2) - overlap_len + local_idx
        global_byte   = global_sample

        save_detection(local_idx, global_byte,
                       c1_ratio, c3_ratio, empty_count, signal)

    return total_c1, total_c2, total_c3, total_c4


#main 
condition = True
while condition:
    BinaryFile = "C:/Users/ucef-/Desktop/Captures/ForRtl/output_8bit.bin"
    file_size  = os.path.getsize(BinaryFile)
    print("=====================>>>>>>>><<<<<<<==================")
    print(f"\nWelcome to ADS-B Visualizer >>> your file is of size {file_size}")
    print("=====================>>>>>>>><<<<<<<==================")
    print("\nWelcome to ADS-B Visualizer >>>")
    print("\nPress 0 to exit")

    NSamples   = int(input("Enter the number of samples in plot (20, 100, 2000): ")) * 2
    timeOfPlot = (NSamples / 2) * 0.5
    SliceN     = input(
        f"Select the slice you want to visualize by entering the X multiple "
        f"integer of the {timeOfPlot} micro sec: "
    )

    if int(SliceN) == 0:
        break

    # scaler for plot x-axis ticks (unchanged)
    if NSamples <= 50:
        scaler = 1
    elif NSamples <= 200:
        scaler = 2
    elif NSamples <= 1000:
        scaler = 50
    else:
        scaler = 100

    
    file_size  = os.path.getsize(BinaryFile)
    all_results["capture_file"] = BinaryFile

    print(f"\nFile: {BinaryFile}  ({file_size/1e6:.1f} MB)")

    CHUNK_SAMPLES = 100_000     # 100k IQ pairs = 200k bytes per chunk
    OVERLAP       = 256         # samples carried over to next chunk
    DC_Shift      = 0.7

    buffer      = []            # overlap buffer from previous chunk
    byte_offset = 0             # current file position in bytes
    total_c1 = total_c2 = total_c3 = total_c4 = 0

    # ── Store ONE chunk for the visualiser (the slice the user asked for) ──
    vis_start_byte = NSamples * (int(SliceN) - 1)
    vis_Magnitude  = []
    vis_CorrelationValues = None

    with open(BinaryFile, "rb") as f:

        while byte_offset < file_size:

            raw = f.read(CHUNK_SAMPLES * 2)     # read 200k bytes
            if not raw:
                break

            # ── Convert bytes → magnitude (same formula as your original) ──
            chunk_mag = []
            for i in range(0, len(raw) - 1, 2):
                I_val = raw[i]     - 127.5
                Q_val = raw[i + 1] - 127.5
                chunk_mag.append(math.sqrt(I_val * I_val + Q_val * Q_val) - DC_Shift)

            # ── Prepend overlap from previous chunk ──
            signal = buffer + chunk_mag

            # ── Capture the slice the user wants for the visualiser ──
            if vis_start_byte >= byte_offset and \
               vis_start_byte < byte_offset + len(raw):
                local_start = (vis_start_byte - byte_offset) // 2
                vis_Magnitude = signal[local_start: local_start + NSamples // 2]
                vis_CorrelationValues = np.correlate(
                    vis_Magnitude, preamble, mode="valid"
                )

            # ── Run the 4-criterion detector on this chunk ──
            total_c1, total_c2, total_c3, total_c4 = process_chunk(
                signal, byte_offset, len(buffer),
                total_c1, total_c2, total_c3, total_c4
            )

            # ── Update running totals in results file ──
            all_results["total_c1"] = total_c1
            all_results["total_c2"] = total_c2
            all_results["total_c3"] = total_c3
            all_results["total_final"] = total_c4

            # ── Carry overlap to next chunk ──
            buffer      = chunk_mag[-OVERLAP:]
            byte_offset += len(raw)

            print(f"  Progress: {byte_offset/1e6:.1f} MB / "
                  f"{file_size/1e6:.0f} MB   "
                  f"confirmed={total_c4}", end="\r")

    print(f"\n\nDone. C1={total_c1}  C2={total_c2}  "
          f"C3={total_c3}  Final={total_c4}")
    print(f"Results saved to {RESULTS_FILE}")

    # ── Use vis_Magnitude for the visualiser below (same as your original) ──
    Magnitude        = vis_Magnitude  if vis_Magnitude  else []
    CorrelationValues = vis_CorrelationValues if vis_CorrelationValues is not None \
                        else np.array([0])
    limit = len(Magnitude) - 17
    start_byte = vis_start_byte

    # ════════════════════════════════════════════════════════════════════════
    # EVERYTHING BELOW THIS LINE IS YOUR ORIGINAL VISUALISER CODE UNCHANGED
    # ════════════════════════════════════════════════════════════════════════

    def Decoding(binmsg):
        for key, value in binmsg.items():
            print(f"\n{'='*50}")
            print(f"REPORT FOR INDEX: {key}")
            try:
                bin_str = str(value)
                hex_msg = pms.util.bin2hex(bin_str)
                decoded = pms.decode(hex_msg)
                is_valid = decoded.get("crc_valid", False)
                tc   = decoded.get("typecode")
                icao = decoded.get("icao")
                print(f"Hex Message:  {hex_msg}")
                print(f"CRC Result:   {'Valid' if is_valid else 'Corrupted'}")
                print(f"ICAO Address: {icao}")
                print(f"Typecode:     {tc}")
                print(f"{'-'*50}")
                if not is_valid or tc is None:
                    print("Skipping detailed parse (Invalid CRC or Unknown Typecode).")
                    continue
                if 1 <= tc <= 4:
                    print(f"[IDENTIFICATION]")
                    print(f"Callsign: {decoded.get('callsign', 'N/A')}")
                elif 5 <= tc <= 8:
                    print(f"[SURFACE POSITION]")
                    gs = decoded.get('groundspeed')
                    if gs is not None:
                        print(f"Ground Speed: {gs} knots ({round(gs*1.852,2)} km/h)")
                    lat = decoded.get('latitude')
                    lon = decoded.get('longitude')
                    if lat is not None and lon is not None:
                        print(f"Latitude:  {lat}")
                        print(f"Longitude: {lon}")
                    else:
                        if len(bin_str) >= 88:
                            print(f"Raw CPR Lat: {int(bin_str[54:71],2)}")
                            print(f"Raw CPR Lon: {int(bin_str[71:88],2)}")
                elif 9 <= tc <= 18:
                    print(f"[AIRBORNE POSITION]")
                    print(f"Altitude: {decoded.get('altitude','N/A')} ft")
                    lat = decoded.get('latitude')
                    lon = decoded.get('longitude')
                    if lat is not None and lon is not None:
                        print(f"Latitude:  {lat}")
                        print(f"Longitude: {lon}")
                    else:
                        if len(bin_str) >= 88:
                            print(f"Raw CPR Lat: {int(bin_str[54:71],2)}")
                            print(f"Raw CPR Lon: {int(bin_str[71:88],2)}")
                elif tc == 19:
                    print(f"[AIRBORNE VELOCITY]")
                    gs = decoded.get('groundspeed')
                    if gs is not None:
                        print(f"Ground Speed: {gs} knots ({round(gs*1.852,2)} km/h)")
                        print(f"Track Angle:  {decoded.get('track')}°")
                    airspeed = decoded.get('airspeed')
                    if airspeed is not None:
                        print(f"Air Speed: {airspeed} knots ({round(airspeed*1.852,2)} km/h)")
                        print(f"Heading:   {decoded.get('heading')}°")
                    vrate_fpm = decoded.get('vertical_rate')
                    if vrate_fpm is not None:
                        vrate_ms = round((vrate_fpm * 0.3048) / 60, 2)
                        status = "Climbing" if vrate_fpm > 0 else "Descending"
                        print(f"Vertical Rate: {vrate_fpm} fpm ({status}) → {abs(vrate_ms)} m/s")
                elif tc == 31:
                    print(f"[OPERATIONAL STATUS]")
                    print(f"Capability: {decoded.get('capability','N/A')}")
            except Exception as e:
                print(f"Error at index {key}: {e}")

    # Build msg from confirmed detections for decoding
    msg = {}
    for det in all_results["detections"]:
        # re-map global byte back to vis_Magnitude local index for display
        g_byte = det["global_byte_offset"]
        local  = (g_byte - vis_start_byte) // 2
        if 0 <= local < len(Magnitude) - 240:
            msg[local] = Magnitude[local + 16: local + 240]

    try:
        Bit_Slicer(msg)
    except Exception:
        print("\nCould not slice message bits — increase samples")
    print(msg)
    Decoding(msg)
    limit = NSamples//2
    if limit < 2000:
        plt.style.use('_mpl-gallery')
        
        class SignalShifter:
            def __init__(self, stem_container, base_xx, base_yy):
                self.shift_amount = 0
                self.stem_container = stem_container
                self.base_xx = base_xx
                self.base_yy = base_yy
            def Update_position(self):
                #new X positions
                new_xx = self.base_xx + self.shift_amount
                
                #Update the stem markers (the dots)
                self.stem_container.markerline.set_xdata(new_xx)#the circle at the top of the stick
                
                #Update the stem lines (the vertical sticks)
                new_segments = [[[x, 0], [x, y]] for x, y in zip(new_xx, self.base_yy)] #[[x, 0], [x, y]] this represnet the coordinate 
                self.stem_container.stemlines.set_segments(new_segments)#of the starting and ending point of the vertical line stick
                #zip takes your new x positions and your original heights (y) and pairs them up like a zipper. 
                #If x=5 and y=0.5, they become a pair: (5, 0.5).
                
                # 5. Redraw the plot!
                plt.draw()

            def Shift_by_button(self, event):
                
                self.shift_amount += 1
                self.Update_position()
                #print(f"Shift amount: {self.shift_amount}")
                
                
            def Shift_by_TextBox(self, text):
                try:
                    self.shift_amount=int(text)
                    self.Update_position()
                except:
                    print("enter an integer")


        Samples = int(NSamples/2)-1
        x = np.arange(0, int(Samples))
        y = Magnitude

        # the preamble pattern 
        xx = np.arange(0, 26)
        yy = np.zeros(26) 
        yy[0], yy[2], yy[7], yy[9],yy[16],yy[19],yy[21],yy[23],yy[24] = 3, 3, 3, 3, 3, 3, 3, 3, 3

        Last_index = len(CorrelationValues)
        Corr_x = range(0,Last_index)
        
        Corr_y = CorrelationValues

        fig2 = plt.figure(figsize=(6,4))
        cx = fig2.add_axes([0.07, 0.1, 1, 1])

        fig = plt.figure(figsize=(6, 4))
        ax = fig.add_axes([0.07, 0.1, 1, 1])

        
        
        # Plot signal and stem
        ax.plot(x, y, label="Signal")
        line = ax.stem(xx, yy, linefmt='red', label="Preamble pulses")

        ax.set_xlabel(f"IQ SAMPLES (A sample in 0.5 micro sec) S:{int(start_byte/2)}")
        ax.set_ylabel("Magnitude ")

        ax.set(xlim=(0, Samples), xticks= scaler*np.arange(1, Samples/scaler),
               ylim=(0, 12), yticks=np.arange(1, 12))

        #  Button
        # Pass the stem container (line) and base arrays into the class
        callback = SignalShifter(line, xx, yy)

        ax_button = plt.axes([0.04, 0.005, 0.1, 0.04]) # [left, bottom, width, height]
        btn = Button(ax_button, 'Shift', color='lightgray', hovercolor='white')
        btn.on_clicked(callback.Shift_by_button)
        box = plt.axes([0.87, 0.005, 0.1, 0.04])
        InputShift= TextBox(box, "jump to: ", initial = "0")
        InputShift.on_submit(callback.Shift_by_TextBox)
        cx.plot(Corr_x,Corr_y, color="red")
        cx.set(xlim=(0, Last_index), xticks= scaler*np.arange(1, Last_index/scaler),
               ylim=(0, 500), yticks= range(0,500,50)) 
        
        plt.grid(visible=True)
        plt.show()
        #correlation graph 


        
        
        #plt.grid(visible=True)
        #plt.show()

    else :
        print("\n Reduce the number of Samples in plot -must be lower than 2000 - in order to VISUALIZE!")
