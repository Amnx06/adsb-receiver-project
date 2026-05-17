"""
train_cnn.py
============
1-D Convolutional Neural Network for ADS-B Mode-S preamble detection.

Physical background
-------------------
The Mode-S preamble is the fixed 16-chip pattern 1010000101000000
transmitted at 1090 MHz.  At 2 MSps every chip spans 2 samples so the
preamble occupies the first 32 samples of a 256-sample window.  A
matched-filter or energy-threshold detector breaks down at low SNR
because the preamble amplitude is indistinguishable from noise peaks.
A 1-D CNN learns a *template* of the preamble shape directly from data,
and can exploit the temporal structure (which samples are HIGH, which
are LOW) in a way a simple threshold cannot.

Why 1-D CNN (and not other options)
-------------------------------------
| Approach        | Pros                          | Cons                        |
|-----------------|-------------------------------|-----------------------------|
| Threshold       | Zero training, real-time      | Fails at low SNR            |
| Matched filter  | Optimal for known AWGN signal | Needs exact freq sync       |
| 1-D CNN         | Learns from data, robust SNR  | Needs training data         |
| RNN/LSTM        | Good for long sequences       | Slower, harder to tune      |
| 2-D CNN (image) | Works on spectrograms         | More data, slower           |

→ 1-D CNN is the right choice: the input is a 1-D time series of
  magnitude values, the pattern is short and fixed (32 samples), and
  the class is binary.  Training on synthetic data is fast and
  immediately applicable to real SDR captures.

Architecture overview
----------------------
Input  (256, 1)
  ↓
Conv1D(32 filters, kernel=8, ReLU)   — learns 8-sample local pulse shapes
  ↓
BatchNorm → MaxPool(2)               — halves sequence length
  ↓
Conv1D(64 filters, kernel=5, ReLU)   — combines pulse shapes
  ↓
BatchNorm → MaxPool(2)
  ↓
Conv1D(128 filters, kernel=3, ReLU)  — high-level preamble features
  ↓
GlobalMaxPool                        — collapses time axis, keeps best activation
  ↓
Dense(64, ReLU) → Dropout(0.3)
  ↓
Dense(1, Sigmoid)                    — P(preamble present)

Output: probability in [0, 1].  Threshold at 0.5 → {0, 1} prediction.
"""

# ── 0. Imports ────────────────────────────────────────────────────────────────
import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"   # suppress TF info logs

import numpy as np
import matplotlib
matplotlib.use("Agg")                       # headless rendering
import matplotlib.pyplot as plt

from sklearn.model_selection import train_test_split
from sklearn.metrics          import (classification_report,
                                      confusion_matrix,
                                      roc_curve, auc)

import tensorflow as tf
from tensorflow.keras import layers, models, callbacks, optimizers

# Local generator
from Generate_iq import build_dataset

# ── Reproducibility ───────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)
tf.random.set_seed(SEED)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Build dataset
# ══════════════════════════════════════════════════════════════════════════════
def load_data():
    """
    Generate a balanced multi-SNR dataset.

    SNR range:  0 dB – 20 dB in 5-dB steps
    Samples:    1000 per class per SNR  ×  5 SNR levels  ×  2 classes
                = 10 000 total samples

    At 0 dB the preamble is buried in noise → forces the CNN to learn
    the pattern, not just energy.  At 20 dB the preamble is very clear
    → teaches the template.  Mixing SNRs makes the model robust.
    """
    print("[Step 1] Generating synthetic IQ dataset ...")

    # Training+validation data: wide SNR spread
    snr_train = [0, 5, 10, 15, 20]
    X, y = build_dataset(snr_train, n_per_class_per_snr=1000)

    # Held-out test set at medium SNR (realistic operating point)
    snr_test = [8, 12, 16]
    X_test_raw, y_test = build_dataset(snr_test, n_per_class_per_snr=500)

    # Shuffle training data
    idx   = np.random.permutation(len(X))
    X, y  = X[idx], y[idx]

    # Train / validation split  (80 / 20)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=SEED, stratify=y
    )

    print(f"  Train samples : {len(X_train)}   "
          f"(preamble: {y_train.sum()}, noise: {(y_train==0).sum()})")
    print(f"  Val   samples : {len(X_val)}")
    print(f"  Test  samples : {len(X_test_raw)}")

    return X_train, X_val, X_test_raw, y_train, y_val, y_test


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Pre-processing
# ══════════════════════════════════════════════════════════════════════════════
def preprocess(X_train, X_val, X_test):
    """
    Normalise magnitude samples to zero-mean, unit-variance using
    statistics from the training set ONLY.

    Why normalise?
    --------------
    Neural network weights are initialised near zero.  If input values
    are large (e.g. 0 – 5.0 range) the gradients become too large and
    training is unstable.  Normalising to ~N(0,1) keeps gradients
    well-behaved and lets the model train faster.

    Important: fit the scaler only on training data.  Applying training
    statistics to validation/test simulates a real deployment where you
    do not know future data statistics.
    """
    mu  = X_train.mean()
    std = X_train.std()

    print(f"\n[Step 2] Normalisation  μ={mu:.4f}  σ={std:.4f}")

    X_train_n = (X_train - mu) / (std + 1e-8)
    X_val_n   = (X_val   - mu) / (std + 1e-8)
    X_test_n  = (X_test  - mu) / (std + 1e-8)

    # Keras Conv1D expects shape (batch, timesteps, channels)
    # Add a channel dimension: (N, 256) → (N, 256, 1)
    X_train_n = X_train_n[..., np.newaxis]
    X_val_n   = X_val_n  [..., np.newaxis]
    X_test_n  = X_test_n [..., np.newaxis]

    return X_train_n, X_val_n, X_test_n, mu, std


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Build 1-D CNN
# ══════════════════════════════════════════════════════════════════════════════
def build_model(input_length: int = 256) -> tf.keras.Model:
    """
    Construct the 1-D CNN.

    Layer-by-layer explanation
    --------------------------
    Conv1D(32, 8):
        32 learnable 8-sample filters slide across the input.
        Each filter learns to respond to a specific local shape
        (e.g. a rising edge, a plateau).
        Kernel size 8 = 4 chips at 2 sps — covers one chip transition.

    BatchNormalization:
        Normalises activations across the batch after each Conv layer.
        Prevents internal covariate shift and allows higher learning rates.

    MaxPooling1D(2):
        Takes the maximum value in every 2-sample window.
        Halves the sequence length → reduces computation and gives
        translation invariance (the preamble might start 1 sample early).

    Conv1D(64, 5):
        64 filters of width 5 applied to the pooled features.
        At this stage each "sample" already represents 2 raw samples so
        the receptive field is 5×2=10 raw samples — covers ~5 chips.

    Conv1D(128, 3):
        128 filters see features that span 3×4=12 raw samples.
        By this layer the CNN has a receptive field of ~32 samples —
        exactly the preamble length.  This is intentional.

    GlobalMaxPooling1D:
        Takes the maximum activation across ALL time positions.
        The CNN is now position-agnostic: it doesn't matter WHERE in
        the window the preamble is, only whether the pattern was seen.
        This is better than Flatten() because it avoids memorising
        position.

    Dense(64) + Dropout(0.3):
        Fully connected layer to combine spatial features.
        Dropout randomly zeroes 30% of neurons during training —
        prevents overfitting to training-set noise realisations.

    Dense(1, sigmoid):
        Single probability output.  sigmoid squashes to [0,1].
        Threshold at 0.5:  P > 0.5 → preamble detected.
    """
    inp = layers.Input(shape=(input_length, 1), name="magnitude_input")

    # ── Block 1 ───────────────────────────────────────────────────────────
    x = layers.Conv1D(32, kernel_size=8, padding="same",
                      activation="relu", name="conv1")(inp)
    x = layers.BatchNormalization(name="bn1")(x)
    x = layers.MaxPooling1D(pool_size=2, name="pool1")(x)

    # ── Block 2 ───────────────────────────────────────────────────────────
    x = layers.Conv1D(64, kernel_size=5, padding="same",
                      activation="relu", name="conv2")(x)
    x = layers.BatchNormalization(name="bn2")(x)
    x = layers.MaxPooling1D(pool_size=2, name="pool2")(x)

    # ── Block 3 ───────────────────────────────────────────────────────────
    x = layers.Conv1D(128, kernel_size=3, padding="same",
                      activation="relu", name="conv3")(x)
    x = layers.BatchNormalization(name="bn3")(x)

    # ── Global pooling → Dense head ───────────────────────────────────────
    x = layers.GlobalMaxPooling1D(name="global_max_pool")(x)
    x = layers.Dense(64, activation="relu", name="dense1")(x)
    x = layers.Dropout(0.3, name="dropout")(x)
    out = layers.Dense(1, activation="sigmoid", name="output")(x)

    model = models.Model(inputs=inp, outputs=out, name="preamble_cnn")
    return model


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Train
# ══════════════════════════════════════════════════════════════════════════════
def train_model(model, X_train, y_train, X_val, y_val):
    """
    Compile and train the model.

    Optimiser — Adam:
        Adaptive learning rate.  Works well without manual LR tuning.

    Loss — BinaryCrossentropy:
        Standard loss for binary classification.
        BCE = -[y·log(p) + (1-y)·log(1-p)]
        Penalises confident wrong predictions very heavily.

    Callbacks:
        EarlyStopping: stops training if val_loss does not improve for
            10 epochs → prevents overfitting, saves time.
        ReduceLROnPlateau: halves the learning rate if val_loss
            plateaus for 5 epochs → fine-tunes near the optimum.
        ModelCheckpoint: saves the best weights (by val_loss) so we
            can restore them after early stopping.
    """
    print("\n[Step 4] Compiling model ...")

    model.compile(
        optimizer  = optimizers.Adam(learning_rate=1e-3),
        loss       = "binary_crossentropy",
        metrics    = ["accuracy",
                      tf.keras.metrics.AUC(name="auc"),
                      tf.keras.metrics.Precision(name="precision"),
                      tf.keras.metrics.Recall(name="recall")]
    )
    model.summary()

    cb_list = [
        callbacks.EarlyStopping(monitor="val_loss", patience=10,
                                restore_best_weights=True, verbose=1),
        callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                    patience=5, min_lr=1e-6, verbose=1),
        callbacks.ModelCheckpoint("best_preamble_cnn.keras",
                                  monitor="val_loss", save_best_only=True,
                                  verbose=0)
    ]

    print("\n[Step 4] Training ...")
    history = model.fit(
        X_train, y_train,
        validation_data = (X_val, y_val),
        epochs          = 60,
        batch_size      = 64,
        callbacks       = cb_list,
        verbose         = 1
    )
    return history


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Evaluate
# ══════════════════════════════════════════════════════════════════════════════
def evaluate_model(model, X_test, y_test):
    """
    Full evaluation on the held-out test set.

    Metrics explained
    -----------------
    Accuracy  : fraction of correct predictions (misleading if imbalanced)
    Precision : of all predicted preambles, what fraction were real?
                → low precision = many false alarms
    Recall    : of all real preambles, what fraction did we catch?
                → low recall = many missed preambles
    F1-score  : harmonic mean of precision and recall
    AUC-ROC   : area under the ROC curve. 0.5 = random, 1.0 = perfect.
    """
    print("\n[Step 5] Evaluating on test set ...")
    y_prob = model.predict(X_test, verbose=0).flatten()
    y_pred = (y_prob >= 0.5).astype(int)

    print("\nClassification Report:")
    print(classification_report(y_test, y_pred,
                                 target_names=["noise", "preamble"]))

    cm = confusion_matrix(y_test, y_pred)
    print("Confusion Matrix:")
    print("             Pred:noise  Pred:preamble")
    print(f"True:noise       {cm[0,0]:5d}          {cm[0,1]:5d}")
    print(f"True:preamble    {cm[1,0]:5d}          {cm[1,1]:5d}")

    fpr, tpr, _ = roc_curve(y_test, y_prob)
    roc_auc     = auc(fpr, tpr)
    print(f"\nAUC-ROC: {roc_auc:.4f}")

    return y_prob, fpr, tpr, roc_auc


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Plot results
# ══════════════════════════════════════════════════════════════════════════════
def plot_results(history, fpr, tpr, roc_auc, out_dir="/mnt/user-data/outputs"):
    """Save four diagnostic figures."""
    os.makedirs(out_dir, exist_ok=True)

    # ── Figure 1: Training curves ─────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    axes[0].plot(history.history["loss"],     label="Train Loss")
    axes[0].plot(history.history["val_loss"], label="Val Loss")
    axes[0].set_title("Binary Cross-Entropy Loss")
    axes[0].set_xlabel("Epoch");  axes[0].set_ylabel("Loss")
    axes[0].legend();             axes[0].grid(True, alpha=0.3)

    axes[1].plot(history.history["accuracy"],     label="Train Acc")
    axes[1].plot(history.history["val_accuracy"], label="Val Acc")
    axes[1].set_title("Accuracy")
    axes[1].set_xlabel("Epoch");  axes[1].set_ylabel("Accuracy")
    axes[1].legend();             axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    p1 = os.path.join(out_dir, "01_training_curves.png")
    plt.savefig(p1, dpi=150);  plt.close()

    # ── Figure 2: ROC curve ───────────────────────────────────────────────
    plt.figure(figsize=(6, 5))
    plt.plot(fpr, tpr, color="steelblue", lw=2,
             label=f"AUC = {roc_auc:.4f}")
    plt.plot([0, 1], [0, 1], "k--", lw=1, label="Random classifier")
    plt.xlabel("False Positive Rate (False Alarm)")
    plt.ylabel("True Positive Rate (Detection)")
    plt.title("ROC Curve — Preamble Detector")
    plt.legend(loc="lower right");  plt.grid(True, alpha=0.3)
    p2 = os.path.join(out_dir, "02_roc_curve.png")
    plt.savefig(p2, dpi=150);  plt.close()

    # ── Figure 3: Precision / Recall vs epoch ─────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].plot(history.history["precision"],     label="Train Precision")
    axes[0].plot(history.history["val_precision"], label="Val Precision")
    axes[0].set_title("Precision");  axes[0].set_xlabel("Epoch")
    axes[0].legend();                axes[0].grid(True, alpha=0.3)

    axes[1].plot(history.history["recall"],     label="Train Recall")
    axes[1].plot(history.history["val_recall"], label="Val Recall")
    axes[1].set_title("Recall");  axes[1].set_xlabel("Epoch")
    axes[1].legend();             axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    p3 = os.path.join(out_dir, "03_precision_recall.png")
    plt.savefig(p3, dpi=150);  plt.close()

    # ── Figure 4: Sample signal visualisation ────────────────────────────
    from Generate_iq import generate_sample
    fig, axes = plt.subplots(2, 1, figsize=(12, 5))
    mag_p, _ = generate_sample(snr_db=10, label=1)
    mag_n, _ = generate_sample(snr_db=10, label=0)

    axes[0].plot(mag_p, color="royalblue", linewidth=0.8)
    axes[0].axvspan(0, 31, alpha=0.15, color="green", label="Preamble zone")
    axes[0].set_title("Preamble present  (SNR = 10 dB)")
    axes[0].set_xlabel("Sample index");  axes[0].set_ylabel("|IQ|")
    axes[0].legend();                    axes[0].grid(True, alpha=0.3)

    axes[1].plot(mag_n, color="tomato", linewidth=0.8)
    axes[1].set_title("Noise only  (SNR = 10 dB)")
    axes[1].set_xlabel("Sample index");  axes[1].set_ylabel("|IQ|")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    p4 = os.path.join(out_dir, "04_sample_signals.png")
    plt.savefig(p4, dpi=150);  plt.close()

    print(f"\n[Step 6] Figures saved:\n  {p1}\n  {p2}\n  {p3}\n  {p4}")
    return [p1, p2, p3, p4]


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Per-SNR accuracy sweep
# ══════════════════════════════════════════════════════════════════════════════
def snr_sweep(model, mu, std, out_dir="/mnt/user-data/outputs"):
    """
    Evaluate detection accuracy at individual SNR points.
    This gives you the classical 'Pd vs SNR' curve used in radar.
    """
    from Generate_iq import build_dataset
    snr_points = list(range(0, 22, 2))   # 0, 2, 4 … 20 dB
    accs = []

    print("\n[Step 7] SNR sweep ...")
    for snr in snr_points:
        Xs, ys = build_dataset([snr], n_per_class_per_snr=300)
        Xs_n   = ((Xs - mu) / (std + 1e-8))[..., np.newaxis]
        yp     = (model.predict(Xs_n, verbose=0).flatten() >= 0.5).astype(int)
        acc    = (yp == ys).mean()
        accs.append(acc)
        print(f"  SNR = {snr:3d} dB  accuracy = {acc*100:.1f}%")

    plt.figure(figsize=(7, 4))
    plt.plot(snr_points, [a * 100 for a in accs],
             "o-", color="steelblue", lw=2)
    plt.axhline(90, color="red", ls="--", lw=1, label="90 % target")
    plt.xlabel("SNR (dB)");  plt.ylabel("Accuracy (%)")
    plt.title("Detection Accuracy vs SNR")
    plt.legend();  plt.grid(True, alpha=0.3)
    p5 = os.path.join(out_dir, "05_snr_sweep.png")
    plt.savefig(p5, dpi=150);  plt.close()
    print(f"  Saved: {p5}")
    return p5


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Save model and normalisation parameters
# ══════════════════════════════════════════════════════════════════════════════
def save_artifacts(model, mu, std, out_dir="/mnt/user-data/outputs"):
    """
    Save everything needed to reproduce the exact same predictions:
      - Keras model (weights + architecture)
      - NumPy file with μ and σ for input normalisation

    To load later:
        model = tf.keras.models.load_model('preamble_cnn_final.keras')
        stats = np.load('norm_stats.npy', allow_pickle=True).item()
        mu, std = stats['mu'], stats['std']
    """
    model_path = os.path.join(out_dir, "preamble_cnn_final.keras")
    stats_path = os.path.join(out_dir, "norm_stats.npy")

    model.save(model_path)
    np.save(stats_path, {"mu": float(mu), "std": float(std)})

    print(f"\n[Step 8] Model saved  → {model_path}")
    print(f"         Norm stats   → {stats_path}")
    return model_path, stats_path


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — Inference helper (how to use the model on a new window)
# ══════════════════════════════════════════════════════════════════════════════
def detect_preamble(magnitude_window: np.ndarray,
                    model: tf.keras.Model,
                    mu: float,
                    std: float,
                    threshold: float = 0.5) -> dict:
    """
    Run the trained CNN on a single 256-sample magnitude window.

    Parameters
    ----------
    magnitude_window : np.ndarray shape (256,)  — |IQ| samples
    model            : loaded Keras model
    mu, std          : normalisation statistics from training
    threshold        : decision boundary (default 0.5)

    Returns
    -------
    dict with keys:
        'prob'     : float — raw probability output of the CNN
        'detected' : bool  — True if prob >= threshold
    """
    assert magnitude_window.shape == (256,), \
        f"Expected (256,), got {magnitude_window.shape}"

    x     = (magnitude_window - mu) / (std + 1e-8)
    x     = x.astype(np.float32)[np.newaxis, :, np.newaxis]  # (1,256,1)
    prob  = float(model.predict(x, verbose=0)[0, 0])
    return {"prob": prob, "detected": prob >= threshold}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":

    # 1. Data
    X_train, X_val, X_test, y_train, y_val, y_test = load_data()

    # 2. Pre-process
    X_train_n, X_val_n, X_test_n, mu, std = preprocess(X_train, X_val, X_test)

    # 3. Build model
    print("\n[Step 3] Building 1-D CNN ...")
    model = build_model(input_length=256)

    # 4. Train
    history = train_model(model, X_train_n, y_train, X_val_n, y_val)

    # 5. Evaluate
    y_prob, fpr, tpr, roc_auc = evaluate_model(model, X_test_n, y_test)

    # 6. Plot
    fig_paths = plot_results(history, fpr, tpr, roc_auc)

    # 7. SNR sweep
    snr_path = snr_sweep(model, mu, std)

    # 8. Save artifacts
    model_path, stats_path = save_artifacts(model, mu, std)

    # 9. Quick inference demo
    print("\n[Step 9] Inference demo on 3 fresh samples ...")
    from Generate_iq import generate_sample
    for snr_db in [5, 10, 15]:
        mag, true_label = generate_sample(snr_db, label=1)
        result = detect_preamble(mag, model, mu, std)
        status = "✓ DETECTED" if result["detected"] else "✗ MISSED"
        print(f"  SNR={snr_db:2d} dB  true=1  "
              f"prob={result['prob']:.3f}  {status}")

    mag, true_label = generate_sample(10, label=0)
    result = detect_preamble(mag, model, mu, std)
    status = "✓ CORRECT (no preamble)" if not result["detected"] else "✗ FALSE ALARM"
    print(f"  SNR=10 dB  true=0  "
          f"prob={result['prob']:.3f}  {status}")

    print("\n══ Training complete ══")
    print(f"  AUC-ROC : {roc_auc:.4f}")
    print(f"  Model   : {model_path}")
    all_paths = fig_paths + [snr_path, model_path, stats_path]