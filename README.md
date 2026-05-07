# ADS-B Signal Visualizer

A small Python tool for visualizing IQ samples captured from an SDR tuned to 1090 MHz.

The repository includes:
- `SignalVisualizer.py`: interactive visualization script
- `captures/`: binary IQ capture files (e.g. `capture_Stah1090MHZ.bin`)
- `requirements.txt`: required Python libraries

## What it does

`SignalVisualizer.py` reads raw IQ bytes from a captured ADS-B stream and computes the signal magnitude using:

    magnitude = sqrt(I*I + Q*Q)

It then displays the magnitude waveform and highlights the ADS-B preamble pattern using a Matplotlib plot.

## Features

- interactive sample selection
- slice selection for zooming into a time segment
- magnitude calculation from IQ bytes
- multi-threaded preamble detection
- Matplotlib plot with a shift/jump control

## Requirements

- Python 3
- `numpy`
- `matplotlib`
- `scipy`

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the visualizer from the repository root:

```bash
python SignalVisualizer.py
```

The script asks for:

1. number of samples to plot (`20`, `100`, `2000`, etc.)
2. slice number to visualize (select a time segment)

Enter `0` for the slice number to exit.

> For reliable plotting, keep the number of samples below `2000`.

## How it works

- Reads raw bytes from `captures/capture_Stah1090MHZ.bin`
- Converts alternating bytes into I and Q values
- Computes magnitude and applies a DC shift correction
- Detects ADS-B preamble positions within the selected sample window
- Displays the data with interactive buttons in Matplotlib

## File overview

| File | Description |
|------|-------------|
| `SignalVisualizer.py` | Main visualizer script for ADS-B IQ captures |
| `captures/` | Contains binary SDR capture files tuned to 1090 MHz |
| `requirements.txt` | Python dependencies |

## Notes

- The capture file is expected to contain unsigned 8-bit IQ samples.
- The current sampling rate is assumed to be `2 MSPS`.
- The script is designed for offline analysis of recorded ADS-B data.

## License

This repository does not currently include a license file. Add one if you want to share or distribute the project.
```
