"""Anti-resonant weight generators for the Quantum Golden Pendulum.

Ported from GoldenPendulumMTL (Knopp, 2026) core.py with additions for
quantum-specific modes. All weight families produce vectors on the K-simplex
(sum to 1, all positive) with maximally irrational spacing to prevent
harmonic lock-in between coupled oscillators.

Physics motivation:
    In coupled pendulum systems, rational frequency ratios cause resonance
    (energy transfer / destructive interference). Irrational ratios prevent
    this, keeping oscillators independent. The "most irrational" number is
    the golden ratio φ, because its continued fraction [1;1,1,1,...] converges
    slowest. Higher metallic means and transcendental cocktails extend this
    anti-resonance to multi-dimensional quasiperiodic tori.

    On quantum hardware, these weights set the FIXED rotation angles in the
    first ansatz layer, encoding the anti-resonant structure directly into
    the quantum state preparation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

# ─── Fundamental constants ────────────────────────────────────────────────────
PHI = (1.0 + math.sqrt(5.0)) / 2.0           # Golden ratio: 1.6180339887...
SILVER = 1.0 + math.sqrt(2.0)                # Silver ratio: 2.4142135624...
PLASTIC = 1.3247179572447460259609            # Plastic number (smallest PV)
SUPERGOLDEN = 1.4655712318767680267           # Supergolden ratio
TRIBONACCI = 1.8392867552141611326            # Tribonacci constant
TWO_PHI = 2.0 * PHI                          # 2φ ≈ 3.236 — target equilibrium


def metallic_mean(n: int) -> float:
    """Compute the n-th metallic mean: (n + √(n²+4)) / 2.

    n=1 → Golden φ ≈ 1.618
    n=2 → Silver δ ≈ 2.414
    n=3 → Bronze β₃ ≈ 3.303
    """
    return (n + math.sqrt(n * n + 4)) / 2.0


# ─── Weight mode registry ────────────────────────────────────────────────────

@dataclass
class WeightMode:
    """Descriptor for a weight generation mode."""
    name: str
    base: float
    description: str


WEIGHT_MODES = {
    "golden": WeightMode("golden", PHI, "Golden ratio φ — most balanced anti-resonance"),
    "silver": WeightMode("silver", SILVER, "Silver ratio δ — steep separation"),
    "plastic": WeightMode("plastic", PLASTIC, "Plastic number ρ — gentlest separation"),
    "supergolden": WeightMode("supergolden", SUPERGOLDEN, "Supergolden σ — cubic PV guarantee"),
    "tribonacci": WeightMode("tribonacci", TRIBONACCI, "Tribonacci τ — 3-phase natural fit"),
    "bronze": WeightMode("bronze", metallic_mean(3), "Bronze β₃ — very steep separation"),
    "euler": WeightMode("euler", math.e, "Euler e — transcendental extreme dominance"),
}


def anti_resonant_weights(
    n_oscillators: int,
    base: float = PHI,
) -> np.ndarray:
    """Compute anti-resonant weights using any irrational base.

    The weight for oscillator k is:
        w_k = base^(k-1) / Σ_{j=0}^{K-1} base^j

    Args:
        n_oscillators: Number of coupled oscillators K.
        base: Irrational base for power spacing.

    Returns:
        numpy array of shape (K,) summing to 1.0.
    """
    powers = np.array([base ** k for k in range(n_oscillators)])
    return powers / powers.sum()


def golden_weights(n: int) -> np.ndarray:
    """Golden ratio weights — the default, most balanced anti-resonance."""
    return anti_resonant_weights(n, base=PHI)


def bronze_weights(n: int) -> np.ndarray:
    """Bronze metallic mean β₃ = (3 + √13)/2 ≈ 3.303 — very steep."""
    return anti_resonant_weights(n, base=metallic_mean(3))


def cocktail_weights(
    n: int,
    w1: float = 0.4,
    w2: float = 0.3,
    w3: float = 0.3,
) -> np.ndarray:
    """Transcendental cocktail: 0.4*φ + 0.3*e + 0.3*π.

    Three linearly independent irrationals create a trajectory on a 3D
    quasiperiodic torus — maximum anti-resonance for coupled systems.

    Args:
        n: Number of oscillators.
        w1, w2, w3: Mixing weights for φ, e, π.
    """
    beta = w1 * PHI + w2 * math.e + w3 * math.pi
    return anti_resonant_weights(n, base=beta)


def chaotic_logistic_weights(
    n: int,
    seed: Optional[float] = None,
    burnin: int = 1000,
    floor: float = 0.01,
) -> np.ndarray:
    """Fully ergodic weights from the logistic map at r=4.

    The logistic map x_{t+1} = 4·x_t·(1-x_t) at r=4 is conjugate to the
    Bernoulli shift and ergodic w.r.t. the arcsine distribution. With
    irrational seed 1/φ, the orbit has zero periodic points — the ultimate
    anti-resonance with Lyapunov exponent ln(2).

    Args:
        n: Number of oscillators.
        seed: Initial condition (default: 1/φ ≈ 0.618034).
        burnin: Burn-in iterations to reach the attractor.
        floor: Minimum weight per oscillator (prevents zeros).
    """
    if seed is None:
        seed = 1.0 / PHI  # ≈ 0.618034 — irrational, aperiodic

    x = seed
    for _ in range(burnin):
        x = 4.0 * x * (1.0 - x)

    raw = []
    for _ in range(n):
        x = 4.0 * x * (1.0 - x)
        raw.append(max(x, floor))

    arr = np.array(raw)
    return arr / arr.sum()


def get_weights(mode: str, n: int, **kwargs) -> np.ndarray:
    """Dispatch to the correct weight generator by mode name.

    Args:
        mode: One of "golden", "silver", "plastic", "supergolden",
              "tribonacci", "bronze", "euler", "cocktail", "chaotic_logistic".
        n: Number of oscillators / qubits.
        **kwargs: Passed through to the specific generator.

    Returns:
        numpy array of shape (n,) summing to 1.0.

    Raises:
        ValueError: If mode is unknown.
    """
    if mode == "cocktail":
        return cocktail_weights(n, **kwargs)
    elif mode == "chaotic_logistic":
        return chaotic_logistic_weights(n, **kwargs)
    elif mode in WEIGHT_MODES:
        return anti_resonant_weights(n, base=WEIGHT_MODES[mode].base)
    else:
        raise ValueError(
            f"Unknown weight mode '{mode}'. Available: "
            f"{list(WEIGHT_MODES.keys()) + ['cocktail', 'chaotic_logistic']}"
        )


def weights_to_angles(weights: np.ndarray) -> np.ndarray:
    """Convert anti-resonant weights to fixed rotation angles for the ansatz.

    Maps each weight α_k to a rotation angle θ_k = 2π·α_k. These angles
    are used in the FIXED first layer of the quantum ansatz — they encode
    the anti-resonant structure directly into the quantum state.

    The 2π scaling ensures full coverage of the Bloch sphere's azimuthal
    angle, with irrational spacing preventing any two qubits from aligning.
    """
    return 2.0 * np.pi * weights


def rational_baseline_weights(n: int, mode: str = "uniform") -> np.ndarray:
    """Generate RATIONAL baseline weights for comparison experiments.

    These are the control group: rational weights that WILL produce
    resonance / harmonic lock-in in the coupled oscillator simulation.

    Args:
        n: Number of oscillators.
        mode: "uniform" (1/N each), "harmonic" (1/k normalized), or
              "geometric_half" (1/2^k normalized).
    """
    if mode == "uniform":
        return np.ones(n) / n
    elif mode == "harmonic":
        raw = np.array([1.0 / (k + 1) for k in range(n)])
        return raw / raw.sum()
    elif mode == "geometric_half":
        raw = np.array([0.5 ** k for k in range(n)])
        return raw / raw.sum()
    else:
        raise ValueError(f"Unknown rational baseline: {mode}")
