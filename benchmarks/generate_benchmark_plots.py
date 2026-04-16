"""
Generate benchmark charts from the S3 vs NFS performance results.

Uses the measured results from `benchmark_s3_vs_nfs.py` to produce:
  - benchmark_chart.png  — 3-panel figure: latency bars, speedup bars, summary

Usage:
    python generate_benchmark_plots.py

Output:
    benchmark_chart.png  (saved to repo root)
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # headless — no display required
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path


# ---------------------------------------------------------------------------
# Real measured results from benchmark_s3_vs_nfs.py (median, 3 iterations)
# Machine: Windows 11, MinIO on localhost, local NFS temp dir
# Date: April 2026
# ---------------------------------------------------------------------------

RESULTS = {
    "1 MB": {
        "Upload":        {"s3": 87.3,  "nfs": 2.5},
        "Download":      {"s3": 31.2,  "nfs": 1.9},
        "Copy (step\nhandover)": {"s3": 59.3,  "nfs": 2.3},
    },
    "5 MB": {
        "Upload":        {"s3": 103.3, "nfs": 5.1},
        "Download":      {"s3": 33.9,  "nfs": 4.7},
        "Copy (step\nhandover)": {"s3": 63.1,  "nfs": 5.1},
    },
    "25 MB": {
        "Upload":        {"s3": 214.8, "nfs": 19.5},
        "Download":      {"s3": 73.0,  "nfs": 15.8},
        "Copy (step\nhandover)": {"s3": 112.7, "nfs": 18.9},
    },
}

TOTAL_S3  = 778.6   # ms
TOTAL_NFS =  75.8   # ms

# Feature completion checklist
FEATURES = [
    ("S3 Direct Mount\n(NFS)", True),
    ("OpenHarness\nRuntime",   True),
    ("Codex Python\nSDK",      True),
    ("GCP Terraform\nValidated", True),
    ("S3 vs NFS\nBenchmark",   True),
    ("Harness\nEvaluation",    True),
]


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
S3_COLOR  = "#E05252"   # red
NFS_COLOR = "#4CAF50"   # green
SPEEDUP_COLOR = "#2196F3"  # blue
BG_COLOR  = "#0F1117"
PANEL_BG  = "#1A1D27"
TEXT_COLOR = "#E8EAF6"
GRID_COLOR = "#2A2D3A"

plt.rcParams.update({
    "figure.facecolor":  BG_COLOR,
    "axes.facecolor":    PANEL_BG,
    "axes.edgecolor":    GRID_COLOR,
    "axes.labelcolor":   TEXT_COLOR,
    "axes.titlecolor":   TEXT_COLOR,
    "xtick.color":       TEXT_COLOR,
    "ytick.color":       TEXT_COLOR,
    "text.color":        TEXT_COLOR,
    "grid.color":        GRID_COLOR,
    "grid.linewidth":    0.4,
    "font.family":       "monospace",
    "font.size":         9,
})


# ---------------------------------------------------------------------------
# Build figure: 2×2 grid
#   top-left : latency grouped bars per file size
#   top-right: speedup bar per operation
#   bottom   : feature completion radar / horizontal checklist
# ---------------------------------------------------------------------------
fig = plt.figure(figsize=(18, 12), facecolor=BG_COLOR)
fig.suptitle(
    "AI Agent Workflow Engine — Performance & Feature Completion",
    fontsize=16, fontweight="bold", color=TEXT_COLOR, y=0.98,
)

gs = fig.add_gridspec(2, 3, hspace=0.45, wspace=0.38,
                       left=0.06, right=0.97, top=0.92, bottom=0.06)

ax_latency = fig.add_subplot(gs[0, :2])   # top-left 2/3
ax_speedup = fig.add_subplot(gs[0, 2])    # top-right
ax_total   = fig.add_subplot(gs[1, 0])    # bottom-left
ax_features = fig.add_subplot(gs[1, 1])   # bottom-mid
ax_density  = fig.add_subplot(gs[1, 2])   # bottom-right


# ---------------------
# Panel 1 — Latency comparison, grouped by size
# ---------------------
sizes = list(RESULTS.keys())
ops   = ["Upload", "Download", "Copy (step\nhandover)"]
n_ops = len(ops)
n_sizes = len(sizes)

x = np.arange(n_ops)
width = 0.12
offsets = np.linspace(-(n_sizes - 1) * width, (n_sizes - 1) * width, n_sizes * 2)

for si, size in enumerate(sizes):
    s3_vals  = [RESULTS[size][op]["s3"]  for op in ops]
    nfs_vals = [RESULTS[size][op]["nfs"] for op in ops]
    shade = 0.6 + 0.2 * si
    ax_latency.bar(x + offsets[si * 2],     s3_vals,  width,
                   color=S3_COLOR,  alpha=shade, label=f"S3 {size}" if si == 0 else "_")
    ax_latency.bar(x + offsets[si * 2 + 1], nfs_vals, width,
                   color=NFS_COLOR, alpha=shade, label=f"NFS {size}" if si == 0 else "_")

# Size group labels under the x-ticks
ax_latency.set_xticks(x)
ax_latency.set_xticklabels(ops, fontsize=9)
ax_latency.set_ylabel("Latency (ms)", fontsize=10)
ax_latency.set_title("Operation Latency: S3 HTTP API vs NFS Direct Mount", fontsize=11, pad=10)
ax_latency.yaxis.grid(True, linestyle="--")
ax_latency.set_axisbelow(True)

# Annotate min/max
for si, size in enumerate(sizes):
    for oi, op in enumerate(ops):
        s3  = RESULTS[size][op]["s3"]
        nfs = RESULTS[size][op]["nfs"]
        ax_latency.annotate(
            f"{s3:.0f}",
            xy=(x[oi] + offsets[si * 2], s3),
            xytext=(0, 3), textcoords="offset points",
            ha="center", fontsize=6, color=S3_COLOR,
        )
        ax_latency.annotate(
            f"{nfs:.1f}",
            xy=(x[oi] + offsets[si * 2 + 1], nfs),
            xytext=(0, 3), textcoords="offset points",
            ha="center", fontsize=6, color=NFS_COLOR,
        )

s3_patch  = mpatches.Patch(color=S3_COLOR,  label="S3 HTTP (Boto3)")
nfs_patch = mpatches.Patch(color=NFS_COLOR, label="NFS Direct Mount")
ax_latency.legend(handles=[s3_patch, nfs_patch], loc="upper left", fontsize=8,
                  facecolor=PANEL_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)


# ---------------------
# Panel 2 — Speedup per operation (all sizes combined, show each)
# ---------------------
speedup_labels = []
speedup_values = []
speedup_colors = []

color_map = {"1 MB": "#FF9800", "5 MB": "#2196F3", "25 MB": "#9C27B0"}

for size in sizes:
    for op in ops:
        s3  = RESULTS[size][op]["s3"]
        nfs = RESULTS[size][op]["nfs"]
        label = f"{size}\n{op.split(chr(10))[0]}"
        speedup_labels.append(label)
        speedup_values.append(s3 / nfs)
        speedup_colors.append(color_map[size])

y_pos = np.arange(len(speedup_labels))
bars = ax_speedup.barh(y_pos, speedup_values, color=speedup_colors, alpha=0.85, height=0.6)

for i, (val, bar) in enumerate(zip(speedup_values, bars)):
    ax_speedup.text(val + 0.3, i, f"{val:.1f}x",
                    va="center", fontsize=7.5, color=TEXT_COLOR, fontweight="bold")

ax_speedup.set_yticks(y_pos)
ax_speedup.set_yticklabels(speedup_labels, fontsize=7)
ax_speedup.set_xlabel("Speedup (S3 time ÷ NFS time)", fontsize=8)
ax_speedup.set_title("Speedup per Operation", fontsize=11, pad=10)
ax_speedup.xaxis.grid(True, linestyle="--")
ax_speedup.set_axisbelow(True)
ax_speedup.axvline(1.0, color=TEXT_COLOR, linewidth=0.8, linestyle=":")

patches = [mpatches.Patch(color=color_map[s], label=s) for s in sizes]
ax_speedup.legend(handles=patches, fontsize=7, facecolor=PANEL_BG,
                  edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, loc="lower right")


# ---------------------
# Panel 3 — Total latency head-to-head
# ---------------------
categories = ["S3 HTTP (Boto3)", "NFS Direct Mount"]
values      = [TOTAL_S3, TOTAL_NFS]
colors      = [S3_COLOR, NFS_COLOR]

bars3 = ax_total.bar(categories, values, color=colors, alpha=0.85, width=0.5)
for bar, val in zip(bars3, values):
    ax_total.text(bar.get_x() + bar.get_width() / 2, val + 5,
                  f"{val:.1f} ms", ha="center", fontsize=10,
                  color=TEXT_COLOR, fontweight="bold")

ax_total.set_ylabel("Total latency (ms)", fontsize=9)
ax_total.set_title("Total: All Operations Combined\n(1+5+25 MB upload+download+copy)", fontsize=9, pad=8)
ax_total.yaxis.grid(True, linestyle="--")
ax_total.set_axisbelow(True)

speedup_total = TOTAL_S3 / TOTAL_NFS
ax_total.annotate(
    f"→ {speedup_total:.1f}x faster",
    xy=(1, TOTAL_NFS + 5),
    xytext=(0.5, TOTAL_S3 * 0.55),
    fontsize=11, fontweight="bold", color=NFS_COLOR,
    arrowprops=dict(arrowstyle="->", color=NFS_COLOR, lw=1.5),
)


# ---------------------
# Panel 4 — Feature completion checklist
# ---------------------
ax_features.set_xlim(0, 1)
ax_features.set_ylim(0, 1)
ax_features.axis("off")
ax_features.set_title("Internship Deliverables", fontsize=11, pad=10)

n = len(FEATURES)
row_h = 0.13
y_start = 0.92

for i, (label, done) in enumerate(FEATURES):
    y = y_start - i * row_h
    icon  = "[+]" if done else "[ ]"
    color = NFS_COLOR if done else "#888"
    ax_features.add_patch(
        mpatches.FancyBboxPatch(
            (0.04, y - 0.05), 0.92, row_h - 0.02,
            boxstyle="round,pad=0.01",
            facecolor="#252836", edgecolor=color, linewidth=1.2,
        )
    )
    ax_features.text(0.1, y + 0.01, icon, fontsize=13, va="center")
    ax_features.text(0.22, y + 0.015,
                     label.replace("\n", " "),
                     fontsize=9, va="center", color=TEXT_COLOR)

done_count = sum(1 for _, d in FEATURES if d)
ax_features.text(0.5, 0.02,
                 f"{done_count}/{n} completed  -- All Done!",
                 ha="center", fontsize=10, color=NFS_COLOR, fontweight="bold")


# ---------------------
# Panel 5 — Before/After architecture flow
# ---------------------
ax_density.axis("off")
ax_density.set_title("Step Handover: Before vs After", fontsize=11, pad=10)

# BEFORE box
before_text = (
    "BEFORE  (S3 HTTP)\n"
    "─────────────────\n"
    "Agent A\n"
    "  ↓ PutObject (HTTP)\n"
    "  S3 Bucket\n"
    "  ↓ CopyObject (HTTP)\n"
    "  S3 Bucket\n"
    "  ↓ GetObject (HTTP)\n"
    "Agent B\n\n"
    "3 HTTP round-trips\n"
    "~100–215 ms / step"
)
after_text = (
    "AFTER  (NFS Mount)\n"
    "──────────────────\n"
    "Agent A\n"
    "  ↓ shutil.copy2\n"
    "  /mnt/s3/\n"
    "  ↓ os.open\n"
    "Agent B\n\n\n"
    "0 HTTP calls\n"
    "~2–20 ms / step"
)

ax_density.text(0.08, 0.93, before_text,
                va="top", fontsize=8, color="#FF8A80",
                fontfamily="monospace",
                bbox=dict(facecolor="#2A1A1A", edgecolor=S3_COLOR,
                          boxstyle="round,pad=0.5", linewidth=1.2))

ax_density.text(0.57, 0.93, after_text,
                va="top", fontsize=8, color="#B9F6CA",
                fontfamily="monospace",
                bbox=dict(facecolor="#1A2A1A", edgecolor=NFS_COLOR,
                          boxstyle="round,pad=0.5", linewidth=1.2))

ax_density.text(0.5, 0.04,
                "Set STORAGE_MODE=direct_mount",
                ha="center", fontsize=8, color="#FFD740",
                bbox=dict(facecolor="#2A2500", edgecolor="#FFD740",
                          boxstyle="round,pad=0.3"))


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
OUT = Path(__file__).parent / "benchmark_chart.png"
fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
print(f"Chart saved → {OUT}")
plt.close(fig)
