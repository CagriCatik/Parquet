import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

CSV_PATH = "csv/1_BCDC_5deg.csv"
PARQUET_PATH = "parquet/1_BCDC_5deg.parquet"

# Load CSV and Parquet
df_csv = pd.read_csv(CSV_PATH)
df_parquet = pd.read_parquet(PARQUET_PATH)

print("CSV columns:", df_csv.columns.tolist())
print("Parquet columns:", df_parquet.columns.tolist())

cols = ["Time", "Voltage", "Current", "Temperature", "SOC"]

# Parse Time
for df in (df_csv, df_parquet):
    t = df["Time"]
    if np.issubdtype(t.dtype, np.number):
        df["Time"] = pd.to_timedelta(t, unit="s")
    else:
        df["Time"] = pd.to_datetime(t, errors="coerce")
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# Create 4x4 grid: first two rows CSV, last two rows Parquet
fig, axes = plt.subplots(4, 4, figsize=(15, 10), sharex=False)
fig.suptitle("CSV vs Parquet Comparison (4x4 Grid)", fontsize=14)

# Map columns to rows
pairs = [
    ("Voltage", "Voltage (V)"),
    ("Current", "Current (A)"),
    ("Temperature", "Temperature (C)"),
    ("SOC", "State of Charge (%)"),
]

# Plot CSV data (top 2 rows)
for i, (col, label) in enumerate(pairs):
    for j in range(2):
        ax = axes[j, i]
        ax.plot(df_csv["Time"], df_csv[col], color="tab:blue", linewidth=1)
        ax.set_title(f"{label} (CSV)", fontsize=10)
        if j == 1:
            ax.set_xlabel("Time")
        ax.set_ylabel(label)
        ax.grid(True, linestyle="--", alpha=0.4)

# Plot Parquet data (bottom 2 rows)
for i, (col, label) in enumerate(pairs):
    for j in range(2, 4):
        ax = axes[j, i]
        ax.plot(df_parquet["Time"], df_parquet[col], color="tab:orange", linewidth=1)
        ax.set_title(f"{label} (Parquet)", fontsize=10)
        if j == 3:
            ax.set_xlabel("Time")
        ax.set_ylabel(label)
        ax.grid(True, linestyle="--", alpha=0.4)

# Adjust layout
for ax_row in axes:
    for ax in ax_row:
        ax.tick_params(axis="x", labelrotation=45)

fig.tight_layout(rect=[0, 0, 1, 0.97])
plt.show()
