# ADS-B Receiver Project

Bachelor project — receiving and decoding ADS-B signals at 1090 MHz using RTL-SDR.

## Amine — Systems & Automation

| File | Role |
|------|------|
| `src/capture/batch_controller.py` | Triggers RTL-SDR capture for N seconds |
| `src/capture/simulator.py` | Generates fake .bin files for testing without hardware |
| `src/loader/file_loader.py` | Reads .bin file, converts uint8→float32, subtracts 127.5, returns complex IQ |

## Setup

```bash
pip install -r requirements.txt
```

## Run the loader

```bash
python src/loader/file_loader.py captures/your_file.bin
```

## Dev mode (no hardware)

In `src/capture/batch_controller.py`, set:
```python
USE_SIMULATOR = True   # no hardware
USE_SIMULATOR = False  # real RTL-SDR connected
```
