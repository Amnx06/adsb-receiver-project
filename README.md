# Signal Visualizer

This script plot the magnitude of each IQ sample by using the formula: 
Magnitude = sqrt(I*I+Q*Q)
You can select the scale i.e the number of samples in the x axis, the sampling rate is set at 2 MSPS
You can selec the slice i.e which time period you want to plot by entering the multiple of the original time interval 

## Abderrahim — Filtering and Preamble Detection

| File | Role |
|------|------|
| SignalVisualizer.py | plot and select the scale and slice  |
| captures | has the binary format of the signal over time tunned to 1090MHZ |
## Setup

```bash
pip install -r requirements.txt
```
```
