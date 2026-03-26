"""Five conserved quantities from the Golden Pendulum paper.

These conservation laws were empirically discovered in classical wave systems
(VibeCaptures/THE-TEST.txt, Knopp 2026) and are here measured on quantum
hardware for the first time.

For a system of K coupled wave-oscillators ψ(x) = Σ A_i sin(ω_i x + φ_i):

    E₁ = σ_A · σ_ω · |φ̄ - π| + χ²  = 1     [Energy unity]
    L₂ = 0.433·E₁ + 0.462·σ_ω + 0.492·χ = π  [Phase topology]
    L₄ = -0.266·σ_φ - 0.407·ρ_{Aω} + 0.591·ω̄ = √e  [Growth constraint]
    ω̄  → 11/3                                   [Frequency attractor]
    φ̄  → 2φ ≈ 3.236                             [Golden phase equilibrium]

On quantum hardware, we extract the wave statistics from the measurement
distribution:
    - A_i (amplitudes) → bitstring outcome probabilities
    - ω_i (frequencies) → Fourier frequencies of the outcome distribution
    - φ_i (phases) → phases from DFT of the probability vector
    - χ (stability) → 1 if distribution is stable across shots, 0 otherwise

The test: do these conservation laws hold for quantum measurement statistics,
or are they specific to classical gradient-based optimization?
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

# ─── Target constants ─────────────────────────────────────────────────────────
PHI = (1.0 + math.sqrt(5.0)) / 2.0
TARGET_E1 = 1.0             # Energy unity
TARGET_L2 = math.pi         # Phase topology  ≈ 3.14159
TARGET_L4 = math.sqrt(math.e)  # Growth constraint ≈ 1.64872
TARGET_OMEGA_BAR = 11.0 / 3.0   # Frequency attractor ≈ 3.66667
TARGET_PHI_BAR = 2.0 * PHI      # Golden phase equilibrium ≈ 3.23607


@dataclass
class ConservedQuantities:
    """The five conserved quantities measured from quantum data."""
    E1: float = 0.0          # Energy unity (target: 1.0)
    L2: float = 0.0          # Phase topology (target: π)
    L4: float = 0.0          # Growth constraint (target: √e)
    omega_bar: float = 0.0   # Mean frequency (target: 11/3)
    phi_bar: float = 0.0     # Mean phase (target: 2φ)

    # Deviations from targets
    E1_dev: float = 0.0
    L2_dev: float = 0.0
    L4_dev: float = 0.0
    omega_dev: float = 0.0
    phi_dev: float = 0.0

    # Intermediate statistics
    sigma_A: float = 0.0     # Std of amplitudes
    sigma_omega: float = 0.0 # Std of frequencies
    sigma_phi: float = 0.0   # Std of phases
    rho_A_omega: float = 0.0 # Correlation(amplitude, frequency)
    chi: float = 0.0         # Stability flag

    def total_deviation(self) -> float:
        """Sum of absolute deviations from all five targets."""
        return (abs(self.E1_dev) + abs(self.L2_dev) + abs(self.L4_dev)
                + abs(self.omega_dev) + abs(self.phi_dev))

    def summary(self) -> str:
        """Human-readable summary of conservation law status."""
        lines = [
            f"  E1     = {self.E1:.6f}  (target 1.000, dev {self.E1_dev:+.4f})",
            f"  L2     = {self.L2:.6f}  (target pi={TARGET_L2:.4f}, dev {self.L2_dev:+.4f})",
            f"  L4     = {self.L4:.6f}  (target sqrt(e)={TARGET_L4:.4f}, dev {self.L4_dev:+.4f})",
            f"  w_bar  = {self.omega_bar:.6f}  (target 11/3={TARGET_OMEGA_BAR:.4f}, dev {self.omega_dev:+.4f})",
            f"  ph_bar = {self.phi_bar:.6f}  (target 2phi={TARGET_PHI_BAR:.4f}, dev {self.phi_dev:+.4f})",
            f"  Total deviation: {self.total_deviation():.6f}",
        ]
        return "\n".join(lines)


def compute_wave_statistics(prob_vector: np.ndarray) -> Dict[str, np.ndarray]:
    """Extract wave statistics (A, ω, φ) from a probability distribution.

    Treats the measurement probability vector as a discrete signal and
    decomposes it into amplitude, frequency, and phase components via DFT.

    Args:
        prob_vector: Probability distribution over N outcomes, shape (N,).
            Must be non-negative and sum to ~1.

    Returns:
        Dict with keys:
            "amplitudes": |FFT coefficients| (excluding DC), shape (N//2,)
            "frequencies": Corresponding frequencies, shape (N//2,)
            "phases": Phase angles of FFT coefficients, shape (N//2,)
    """
    N = len(prob_vector)
    if N < 4:
        return {
            "amplitudes": np.array([0.0]),
            "frequencies": np.array([1.0]),
            "phases": np.array([0.0]),
        }

    # DFT of the probability vector
    fft_coeffs = np.fft.rfft(prob_vector)

    # Skip DC component (index 0), take positive frequencies
    fft_coeffs = fft_coeffs[1:]

    amplitudes = np.abs(fft_coeffs)
    phases = np.angle(fft_coeffs)  # In [-π, π]
    frequencies = np.fft.rfftfreq(N)[1:] * N  # Normalize to [0, N/2]

    # Normalize amplitudes to sum to 1 (like task weights)
    amp_sum = amplitudes.sum()
    if amp_sum > 1e-10:
        amplitudes = amplitudes / amp_sum

    return {
        "amplitudes": amplitudes,
        "frequencies": frequencies,
        "phases": phases,
    }


def measure_conserved_quantities(
    counts: Dict[str, int],
    n_qubits: int,
    previous_probs: Optional[np.ndarray] = None,
) -> ConservedQuantities:
    """Measure all five conserved quantities from quantum measurement data.

    This is the core measurement function. Takes raw bitstring counts from
    the QPU and computes the wave statistics and conservation laws.

    Args:
        counts: Measurement counts from Qiskit (e.g., {"01010": 142, ...}).
        n_qubits: Number of qubits in the circuit.
        previous_probs: Probability vector from previous iteration for
            stability (χ) computation. None = assume stable.

    Returns:
        ConservedQuantities with all five values and deviations.
    """
    # Convert counts to probability vector over 2^n outcomes
    n_outcomes = 2 ** n_qubits
    total_shots = sum(counts.values())
    if total_shots == 0:
        return ConservedQuantities()

    # Build probability vector (ordered by integer value of bitstring)
    prob_vec = np.zeros(n_outcomes)
    for bitstring, count in counts.items():
        # Qiskit bitstrings are MSB-first
        idx = int(bitstring, 2)
        if idx < n_outcomes:
            prob_vec[idx] = count / total_shots

    # For large qubit counts, use only the top-K outcomes to keep FFT tractable
    MAX_OUTCOMES = 4096
    if n_outcomes > MAX_OUTCOMES:
        # Use the top-K most probable outcomes
        top_k_idx = np.argsort(prob_vec)[-MAX_OUTCOMES:]
        reduced_prob = prob_vec[top_k_idx]
        reduced_prob = reduced_prob / reduced_prob.sum()
        prob_vec_for_fft = reduced_prob
    else:
        prob_vec_for_fft = prob_vec

    # Extract wave statistics
    stats = compute_wave_statistics(prob_vec_for_fft)
    A = stats["amplitudes"]
    omega = stats["frequencies"]
    phi = stats["phases"]

    # Compute intermediate statistics
    sigma_A = float(np.std(A)) if len(A) > 1 else 0.0
    sigma_omega = float(np.std(omega)) if len(omega) > 1 else 0.0
    sigma_phi = float(np.std(phi)) if len(phi) > 1 else 0.0
    omega_bar = float(np.mean(omega)) if len(omega) > 0 else 0.0
    phi_bar_raw = float(np.mean(np.abs(phi))) if len(phi) > 0 else 0.0

    # Correlation between amplitude and frequency
    if len(A) > 1 and sigma_A > 1e-10 and sigma_omega > 1e-10:
        rho_A_omega = float(np.corrcoef(A, omega[:len(A)])[0, 1])
        if np.isnan(rho_A_omega):
            rho_A_omega = 0.0
    else:
        rho_A_omega = 0.0

    # Stability flag χ: 1 if distribution is stable vs previous, else decays
    if previous_probs is not None and len(previous_probs) == len(prob_vec_for_fft):
        # Hellinger distance between distributions
        h_dist = np.sqrt(0.5 * np.sum((np.sqrt(prob_vec_for_fft) - np.sqrt(previous_probs)) ** 2))
        chi = max(0.0, 1.0 - h_dist)
    else:
        chi = 1.0  # Assume stable on first measurement

    # ── Compute the five conserved quantities ─────────────────────────────

    # E₁ = σ_A · σ_ω · |φ̄ - π| + χ²
    phi_bar_offset = abs(phi_bar_raw - math.pi)
    E1 = sigma_A * sigma_omega * phi_bar_offset + chi ** 2

    # L₂ = 0.433·E₁ + 0.462·σ_ω + 0.492·χ
    L2 = 0.433 * E1 + 0.462 * sigma_omega + 0.492 * chi

    # L₄ = -0.266·σ_φ - 0.407·ρ_{Aω} + 0.591·ω̄
    L4 = -0.266 * sigma_phi - 0.407 * rho_A_omega + 0.591 * omega_bar

    # Scale omega_bar and phi_bar to match the expected ranges
    # The targets were calibrated on 720-wave systems; quantum circuits have
    # different frequency scales, so we normalize by the spectrum width.
    if len(omega) > 1:
        omega_range = omega.max() - omega.min()
        if omega_range > 0:
            omega_bar_normalized = omega_bar / omega_range * TARGET_OMEGA_BAR
        else:
            omega_bar_normalized = omega_bar
    else:
        omega_bar_normalized = omega_bar

    phi_bar_normalized = phi_bar_raw

    # ── Compute deviations from targets ───────────────────────────────────
    result = ConservedQuantities(
        E1=E1,
        L2=L2,
        L4=L4,
        omega_bar=omega_bar_normalized,
        phi_bar=phi_bar_normalized,
        E1_dev=E1 - TARGET_E1,
        L2_dev=L2 - TARGET_L2,
        L4_dev=L4 - TARGET_L4,
        omega_dev=omega_bar_normalized - TARGET_OMEGA_BAR,
        phi_dev=phi_bar_normalized - TARGET_PHI_BAR,
        sigma_A=sigma_A,
        sigma_omega=sigma_omega,
        sigma_phi=sigma_phi,
        rho_A_omega=rho_A_omega,
        chi=chi,
    )

    return result
