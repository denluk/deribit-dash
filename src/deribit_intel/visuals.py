from __future__ import annotations
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

def save_line(df: pd.DataFrame, x: str, y: str, out_path: str, title: str) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(11, 4))
    plt.plot(df[x], df[y])
    plt.title(title)
    plt.xlabel(x)
    plt.ylabel(y)
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()

def save_heatmap(matrix: pd.DataFrame, out_path: str, title: str, y_label: str) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(13, 5))
    plt.imshow(np.log1p(matrix.values), aspect="auto")
    plt.title(title)
    plt.ylabel(y_label)
    plt.xlabel("column index")
    plt.yticks(range(len(matrix.index)), [str(v) for v in matrix.index])
    plt.colorbar(label="log1p(value)")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()
