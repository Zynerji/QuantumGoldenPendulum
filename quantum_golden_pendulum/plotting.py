"""Visualization for the Quantum Golden Pendulum experiment.

Generates publication-quality plots of:
    1. Energy convergence across weight modes
    2. Phase convergence (φ̄ → 2φ) trajectory
    3. Conservation law tracking (E₁, L₂, L₄)
    4. Comparative bar chart (anti-resonant vs baselines)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import numpy as np

try:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from .anti_resonant_weights import PHI, TWO_PHI
from .conserved import TARGET_E1, TARGET_L2, TARGET_L4, TARGET_OMEGA_BAR, TARGET_PHI_BAR
from .optimizer import OptimizationResult

# ─── Style ────────────────────────────────────────────────────────────────────
COLORS = {
    "golden": "#FFD700",
    "bronze": "#CD7F32",
    "cocktail": "#9B59B6",
    "chaotic_logistic": "#E74C3C",
    "baseline_uniform": "#95A5A6",
    "baseline_harmonic": "#7F8C8D",
    "silver": "#C0C0C0",
    "plastic": "#3498DB",
    "supergolden": "#F39C12",
    "tribonacci": "#27AE60",
    "euler": "#2C3E50",
}


def _get_color(mode: str) -> str:
    return COLORS.get(mode, "#333333")


def plot_energy_convergence(
    results: Dict[str, OptimizationResult],
    save_path: Optional[Path] = None,
    title: str = "Energy Convergence",
):
    """Plot energy vs iteration for all weight modes.

    Anti-resonant modes are shown as solid lines, baselines as dashed.
    """
    if not HAS_MPL:
        return

    fig, ax = plt.subplots(1, 1, figsize=(12, 6))

    for mode_name, result in sorted(results.items()):
        is_baseline = mode_name.startswith("baseline_")
        energies = result.energies
        iters = np.arange(1, len(energies) + 1)

        ax.plot(
            iters, energies,
            label=mode_name,
            color=_get_color(mode_name),
            linewidth=2.0 if not is_baseline else 1.5,
            linestyle="-" if not is_baseline else "--",
            alpha=0.9,
        )

        # Mark best point
        ax.scatter(
            [result.best_step], [result.best_energy],
            color=_get_color(mode_name),
            s=60, zorder=5, edgecolors="black", linewidth=0.5,
        )

    ax.set_xlabel("SPSA Iteration", fontsize=12)
    ax.set_ylabel("⟨H⟩ (Energy)", fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_phase_convergence(
    results: Dict[str, OptimizationResult],
    save_path: Optional[Path] = None,
):
    """Plot φ̄ convergence toward 2φ ≈ 3.236 for all modes."""
    if not HAS_MPL:
        return

    fig, ax = plt.subplots(1, 1, figsize=(12, 6))

    # Target line
    ax.axhline(y=TWO_PHI, color="gold", linewidth=2, linestyle=":",
               label=f"2φ = {TWO_PHI:.4f}", alpha=0.8)

    for mode_name, result in sorted(results.items()):
        is_baseline = mode_name.startswith("baseline_")
        phi_bars = result.phi_bars
        iters = np.arange(1, len(phi_bars) + 1)

        ax.plot(
            iters, phi_bars,
            label=mode_name,
            color=_get_color(mode_name),
            linewidth=2.0 if not is_baseline else 1.5,
            linestyle="-" if not is_baseline else "--",
            alpha=0.9,
        )

    ax.set_xlabel("SPSA Iteration", fontsize=12)
    ax.set_ylabel("φ̄ (Mean Phase)", fontsize=12)
    ax.set_title("Phase Convergence → 2φ Equilibrium", fontsize=14, fontweight="bold")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_conserved_quantities(
    results: Dict[str, OptimizationResult],
    save_path: Optional[Path] = None,
):
    """Plot all five conserved quantities in a 2x3 grid."""
    if not HAS_MPL:
        return

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    quantities = [
        ("E₁", "E1", TARGET_E1),
        ("L₂", "L2", TARGET_L2),
        ("L₄", "L4", TARGET_L4),
        ("ω̄", "omega_bar", TARGET_OMEGA_BAR),
        ("φ̄", "phi_bar", TARGET_PHI_BAR),
        ("χ (stability)", "chi", 1.0),
    ]

    for idx, (label, attr, target) in enumerate(quantities):
        ax = axes[idx // 3][idx % 3]

        # Target line
        ax.axhline(y=target, color="gold", linewidth=1.5, linestyle=":", alpha=0.7)

        for mode_name, result in sorted(results.items()):
            is_baseline = mode_name.startswith("baseline_")
            values = np.array([getattr(s.conserved, attr) for s in result.steps])
            iters = np.arange(1, len(values) + 1)

            ax.plot(
                iters, values,
                label=mode_name if idx == 0 else None,
                color=_get_color(mode_name),
                linewidth=1.5 if not is_baseline else 1.0,
                linestyle="-" if not is_baseline else "--",
                alpha=0.8,
            )

        ax.set_title(f"{label} → {target:.4f}", fontsize=11, fontweight="bold")
        ax.set_xlabel("Iteration", fontsize=9)
        ax.grid(True, alpha=0.3)

    # Single legend for the whole figure
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, fontsize=9,
               bbox_to_anchor=(0.5, -0.02))

    fig.suptitle("Conservation Law Tracking", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_comparison_bars(
    results: Dict[str, OptimizationResult],
    save_path: Optional[Path] = None,
):
    """Bar chart comparing final energy and total deviation across modes."""
    if not HAS_MPL:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    modes = sorted(results.keys())
    energies = [results[m].best_energy for m in modes]
    deviations = [
        results[m].steps[-1].conserved.total_deviation() if results[m].steps else 0
        for m in modes
    ]
    colors = [_get_color(m) for m in modes]

    # Energy bars
    bars1 = ax1.bar(modes, energies, color=colors, edgecolor="black", linewidth=0.5)
    ax1.set_ylabel("Best ⟨H⟩", fontsize=12)
    ax1.set_title("Ground State Energy", fontsize=13, fontweight="bold")
    ax1.tick_params(axis="x", rotation=45)
    ax1.grid(axis="y", alpha=0.3)

    # Deviation bars
    bars2 = ax2.bar(modes, deviations, color=colors, edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Σ|deviation|", fontsize=12)
    ax2.set_title("Total Conservation Law Deviation", fontsize=13, fontweight="bold")
    ax2.tick_params(axis="x", rotation=45)
    ax2.grid(axis="y", alpha=0.3)

    fig.suptitle(
        "Anti-Resonant vs Rational Baselines",
        fontsize=14, fontweight="bold",
    )
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()
