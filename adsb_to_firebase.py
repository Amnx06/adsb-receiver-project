"""
adsb_to_firebase.py
────────────────────────────────────────────────────────────────────────────
Drop-in companion to SignalVisualizer.py.

What it does:
  - Takes the `msg` dict that SignalVisualizer already built and bit-sliced
    (the output of  Bit_Slicer(msg)  at line 403 of SignalVisualizer).
  - Re-uses the EXACT same Decoding() logic — but instead of printing,
    it captures every field into a structured dict.
  - Writes results.json to disk.
  - Pushes to Firebase Realtime Database at  adsb/latest  so the Flutter
    app can stream it in real time.

HOW TO USE — paste these lines into SignalVisualizer.py right after
the existing  Decoding(msg)  call (around line 405):

    from adsb_to_firebase import (decode_to_json, add_criterion_counts,
                                  save_json, push_to_firebase)

    result = decode_to_json(msg, Magnitude,
                            capture_file=BinaryFile,
                            start_byte=start_byte)

    add_criterion_counts(result,
                         c1=ExceedThreshold,
                         c2=Theta_2nd_criterion,
                         c3=ThetaD_3rd_criterion,
                         c4=Success_4th_criterion)

    save_json(result)          # writes results.json
    push_to_firebase(result)   # uploads to Firebase adsb/latest

Firebase setup:
  1. Firebase Console → Project Settings → Service Accounts
     → Generate new private key → save as  serviceAccountKey.json
  2. Set FIREBASE_DB_URL below.
────────────────────────────────────────────────────────────────────────────
"""

import json
import math
import datetime
import os
import pyModeS as pms
from pyModeS.util import bin2hex

# ── CONFIGURE ─────────────────────────────────────────────────────────────
FIREBASE_DB_URL = "https://console.firebase.google.com/u/0/project/ads-b-2ef0b/firestore/databases/-default-/data/~2Fadsb~2Flatest"
SERVICE_ACCOUNT = "serviceAccountKey.json"
OUTPUT_JSON     = "results.json"
# ──────────────────────────────────────────────────────────────────────────


# ════════════════════════════════════════════════════════════════════════════
#  decode_to_json
#  Takes the already-bit-sliced `msg` dict and converts every message into
#  a structured record — same fields that Decoding() prints, captured into
#  dicts instead of printed to the console.
# ════════════════════════════════════════════════════════════════════════════

def decode_to_json(msg: dict,
                   magnitude: list,
                   capture_file: str = "captures/capture_Stah1090MHZ.bin",
                   start_byte: int  = 0) -> dict:
    """
    Parameters
    ----------
    msg          : the dict produced by  Bit_Slicer(msg)  in SignalVisualizer.
                   Keys   = shift_index (int)
                   Values = 112-bit binary string  e.g. "10001101..."
    magnitude    : the Magnitude list from SignalVisualizer (used for SNR).
    capture_file : BinaryFile variable from SignalVisualizer.
    start_byte   : start_byte variable from SignalVisualizer.

    Returns
    -------
    A dict matching output_schema.json exactly.
    """

    detections = []

    for key, value in msg.items():

        bin_str = str(value)

        # ── base record ───────────────────────────────────────────────
        record = {
            "shift_index":    key,
            "snr_db":         _compute_snr(key, magnitude),
            "final_decision": True,
            "c1_ratio":       None,
            "c2_match":       True,   # only C4-passing frames reach msg
            "c3_power_ratio": None,
            "c4_null_count":  None,

            "hex_message":    None,
            "crc_valid":      False,
            "icao":           None,
            "typecode":       None,
            "df":             None,
            "message_type":   "UNKNOWN",

            "altitude_ft":    None,
            "altitude_m":     None,
            "latitude":       None,
            "longitude":      None,
            "raw_cpr_lat":    None,
            "raw_cpr_lon":    None,
            "cpr_format":     None,

            "callsign":       None,

            "groundspeed_kt":    None,
            "groundspeed_kmh":   None,
            "track_angle_deg":   None,
            "airspeed_kt":       None,
            "airspeed_kmh":      None,
            "heading_deg":       None,
            "vertical_rate_fpm": None,
            "vertical_rate_ms":  None,
            "vertical_status":   None,
        }

        try:
            # ── same as Decoding() line 266 ───────────────────────────
            hex_msg = bin2hex(bin_str)
            record["hex_message"] = hex_msg

            # ── same as Decoding() line 269 ───────────────────────────
            decoded  = pms.decode(hex_msg)
            is_valid = decoded.get("crc_valid", False)
            tc       = decoded.get("typecode")
            icao     = decoded.get("icao")

            record["crc_valid"] = bool(is_valid)
            record["icao"]      = icao
            record["typecode"]  = tc
            record["df"]        = decoded.get("df")

            # ── same as Decoding() line 282 ───────────────────────────
            if not is_valid or tc is None:
                record["message_type"] = "INVALID_CRC" if not is_valid else "UNKNOWN_TC"
                detections.append(record)
                continue

            # ── IDENTIFICATION  tc 1-4 ────────────────────────────────
            if 1 <= tc <= 4:
                record["message_type"] = "IDENTIFICATION"
                record["callsign"]     = decoded.get("callsign")

            # ── SURFACE POSITION  tc 5-8 ──────────────────────────────
            elif 5 <= tc <= 8:
                record["message_type"] = "SURFACE_POSITION"

                gs = decoded.get("groundspeed")
                if gs is not None:
                    record["groundspeed_kt"]  = round(gs, 2)
                    record["groundspeed_kmh"] = round(gs * 1.852, 2)

                lat = decoded.get("latitude")
                lon = decoded.get("longitude")
                if lat is not None and lon is not None:
                    record["latitude"]  = lat
                    record["longitude"] = lon
                else:
                    if len(bin_str) >= 88:
                        record["raw_cpr_lat"] = int(bin_str[54:71], 2)
                        record["raw_cpr_lon"] = int(bin_str[71:88], 2)

                cpr = decoded.get("cpr_format")
                if cpr is None and len(bin_str) >= 54:
                    cpr = int(bin_str[53])
                record["cpr_format"] = "Odd" if cpr == 1 else "Even"

            # ── AIRBORNE POSITION  tc 9-18 ────────────────────────────
            elif 9 <= tc <= 18:
                record["message_type"] = "AIRBORNE_POSITION"

                alt_ft = decoded.get("altitude")
                if alt_ft is not None:
                    record["altitude_ft"] = alt_ft
                    record["altitude_m"]  = round(alt_ft * 0.3048, 1)

                lat = decoded.get("latitude")
                lon = decoded.get("longitude")
                if lat is not None and lon is not None:
                    record["latitude"]  = lat
                    record["longitude"] = lon
                else:
                    if len(bin_str) >= 88:
                        record["raw_cpr_lat"] = int(bin_str[54:71], 2)
                        record["raw_cpr_lon"] = int(bin_str[71:88], 2)

                cpr = decoded.get("cpr_format")
                if cpr is None and len(bin_str) >= 54:
                    cpr = int(bin_str[53])
                record["cpr_format"] = "Odd" if cpr == 1 else "Even"

            # ── AIRBORNE VELOCITY  tc 19 ──────────────────────────────
            elif tc == 19:
                record["message_type"] = "AIRBORNE_VELOCITY"

                gs = decoded.get("groundspeed")
                if gs is not None:
                    record["groundspeed_kt"]  = round(gs, 2)
                    record["groundspeed_kmh"] = round(gs * 1.852, 2)
                    record["track_angle_deg"] = decoded.get("track")

                airspeed = decoded.get("airspeed")
                if airspeed is not None:
                    record["airspeed_kt"]  = round(airspeed, 2)
                    record["airspeed_kmh"] = round(airspeed * 1.852, 2)
                    record["heading_deg"]  = decoded.get("heading")

                vrate_fpm = decoded.get("vertical_rate")
                if vrate_fpm is not None:
                    record["vertical_rate_fpm"] = vrate_fpm
                    record["vertical_rate_ms"]  = round((vrate_fpm * 0.3048) / 60, 2)
                    record["vertical_status"]   = "Climbing" if vrate_fpm > 0 else "Descending"

            # ── OPERATIONAL STATUS  tc 31 ─────────────────────────────
            elif tc == 31:
                record["message_type"] = "OPERATIONAL_STATUS"
                record["callsign"]     = str(decoded.get("capability", "N/A"))

            else:
                record["message_type"] = f"RESERVED_TC{tc}"

        except Exception as e:
            record["message_type"] = f"DECODE_ERROR: {e}"

        detections.append(record)

    # ── top-level document ─────────────────────────────────────────────
    result = {
        "capture_file":     capture_file,
        "slice_start_byte": start_byte,
        "sample_rate_msps": 2,
        "generated_at":     datetime.datetime.utcnow().isoformat() + "Z",
        "detections":       detections,
        "total_c1":         None,   # filled by add_criterion_counts()
        "total_c2":         None,
        "total_c3":         None,
        "total_c4":         len(msg),
        "total_final":      len(detections),
    }

    return result


# ════════════════════════════════════════════════════════════════════════════
#  add_criterion_counts  (optional but recommended)
#  Call this after decode_to_json() to fill in the C1/C2/C3/C4 counts and
#  the per-detection c1_ratio / c3_power_ratio / c4_null_count values.
# ════════════════════════════════════════════════════════════════════════════

def add_criterion_counts(result: dict,
                         c1: dict,
                         c2: dict,
                         c3: dict,
                         c4: dict) -> None:
    """
    Parameters are the dicts from SignalVisualizer:
      c1 = ExceedThreshold
      c2 = Theta_2nd_criterion
      c3 = ThetaD_3rd_criterion
      c4 = Success_4th_criterion
    """
    result["total_c1"] = len(c1)
    result["total_c2"] = len(c2)
    result["total_c3"] = len(c3)
    result["total_c4"] = len(c4)

    for det in result["detections"]:
        idx = det["shift_index"]
        if idx in c1:
            det["c1_ratio"]       = round(c1[idx], 3)
        if idx in c3:
            det["c3_power_ratio"] = round(c3[idx], 4)
        if idx in c4:
            det["c4_null_count"]  = int(c4[idx])


# ════════════════════════════════════════════════════════════════════════════
#  SNR helper  —  same formula as SNR_Calculation() in SignalVisualizer
# ════════════════════════════════════════════════════════════════════════════

def _compute_snr(index: int, magnitude: list):
    sig   = magnitude[index: index + 224]
    noise = magnitude[max(0, index - 225): max(0, index - 1)]
    if len(sig) < 10 or len(noise) < 10:
        return None
    sig_power   = (sum(sig)   ** 2) / len(sig)
    noise_power = (sum(noise) ** 2) / len(noise)
    if noise_power <= 0:
        return None
    return round(10 * math.log10(sig_power / noise_power), 2)


# ════════════════════════════════════════════════════════════════════════════
#  save_json
# ════════════════════════════════════════════════════════════════════════════

OUTPUT_DIR = "output"
OUTPUT_JSON = "output.json"

def save_json(result: dict, filename: str = OUTPUT_JSON) -> None:
    # Create output folder if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Build full path
    path = os.path.join(OUTPUT_DIR, filename)

    # Save file
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[✓] JSON saved → {path} ({result['total_final']} frame(s))")


# ════════════════════════════════════════════════════════════════════════════
#  push_to_firebase
# ════════════════════════════════════════════════════════════════════════════

def push_to_firebase(result: dict,
                     db_url: str  = FIREBASE_DB_URL,
                     key_file: str = SERVICE_ACCOUNT) -> None:
    """
    Uploads to Firebase Realtime Database path  adsb/latest.
    Flutter AircraftService.streamActiveAircraft() reads from this path.
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, db as fdb
    except ImportError:
        print("[!] Run:  pip install firebase-admin")
        return

    if not os.path.exists(key_file):
        print(f"[!] Key file not found: {key_file}")
        return

    if not firebase_admin._apps:
        cred = firebase_admin.credentials.Certificate(key_file)
        firebase_admin.initialize_app(cred, {"databaseURL": db_url})

    # only CRC-valid frames go to the app
    messages = [
        {
            "icao":              d["icao"],
            "callsign":          d["callsign"],
            "type":              d["message_type"],
            "altitude_ft":       d["altitude_ft"],
            "altitude_m":        d["altitude_m"],
            "latitude":          d["latitude"],
            "longitude":         d["longitude"],
            "raw_cpr_lat":       d["raw_cpr_lat"],
            "raw_cpr_lon":       d["raw_cpr_lon"],
            "cpr_format":        d["cpr_format"],
            "groundspeed_kt":    d["groundspeed_kt"],
            "groundspeed_kmh":   d["groundspeed_kmh"],
            "track_angle_deg":   d["track_angle_deg"],
            "vertical_rate_fpm": d["vertical_rate_fpm"],
            "vertical_rate_ms":  d["vertical_rate_ms"],
            "vertical_status":   d["vertical_status"],
            "snr_db":            d["snr_db"],
            "crc_valid":         d["crc_valid"],
            "shift_index":       d["shift_index"],
        }
        for d in result["detections"]
        if d.get("crc_valid") is True
    ]

    payload = {
        "messages":         messages,
        "capture_file":     result["capture_file"],
        "generated_at":     result["generated_at"],
        "sample_rate_msps": result["sample_rate_msps"],
        "total_final":      result["total_final"],
        "total_c1":         result["total_c1"],
        "total_c2":         result["total_c2"],
        "total_c3":         result["total_c3"],
        "total_c4":         result["total_c4"],
    }

    fdb.reference("adsb/latest").set(payload)
    print(f"[✓] Firebase → adsb/latest  ({len(messages)} valid frame(s))")


# ════════════════════════════════════════════════════════════════════════════
#  SMOKE TEST  (run this file directly to verify it works)
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Smoke test with known ADS-B messages...\n")

    # Simulate what Bit_Slicer(msg) produces in SignalVisualizer:
    # { shift_index: "112-bit-binary-string", ... }
    test_cases = {
        1945473: bin(int("8D02A1AA5839E45D0EC660B4980C", 16))[2:].zfill(112),
        1505439: bin(int("8D02A1AAEA0BD866733C084D56DE", 16))[2:].zfill(112),
    }
    fake_magnitude = [2.5] * 3000

    result = decode_to_json(test_cases, fake_magnitude,
                            capture_file="captures/capture_Stah1090MHZ.bin",
                            start_byte=0)

    save_json(result, "results_test.json")

    print("\n── Detections ──────────────────────────────────")
    for d in result["detections"]:
        print(f"  Index {d['shift_index']:>8}  |  "
              f"ICAO: {d['icao']}  |  "
              f"CRC: {'Valid' if d['crc_valid'] else 'INVALID'}  |  "
              f"Type: {d['message_type']}  |  "
              f"Alt: {d['altitude_ft']} ft  |  "
              f"SNR: {d['snr_db']} dB")
    print(f"\nTotal frames exported: {result['total_final']}")
    print("results_test.json written. Open it to inspect the full schema.")

    import firebase_admin
from firebase_admin import credentials, firestore

# Load service account key
cred = credentials.Certificate("serviceAccountKey.json")

# Initialize app
firebase_admin.initialize_app(cred)

# Get Firestore client
db = firestore.client()

for detection in result["detections"]:
    db.collection("adsb_detections").add(detection)