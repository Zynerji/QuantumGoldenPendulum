"""Coupled pendulum Hamiltonian → Pauli operator decomposition.

Maps the classical coupled-oscillator Hamiltonian from the Golden Pendulum MTL
paper to a qubit Hamiltonian suitable for the Qiskit Estimator primitive.

Classical Hamiltonian:
    H = Σ_i (p_i² / 2)                              [kinetic]
      + (ω₀² / 2) Σ_i (1 - cos θ_i)                [on-site potential]
      + Σ_{i<j} (α_i α_j / N) cos(θ_i - θ_j)       [anti-resonant coupling]

Qubit mapping (one qubit per pendulum):
    cos θ_i  →  Z_i        (diagonal in computational basis)
    sin θ_i  →  X_i        (off-diagonal)
    p_i      →  Y_i        (generates rotations = momentum)

    cos(θ_i - θ_j) = cos θ_i cos θ_j + sin θ_i sin θ_j
                    → Z_i Z_j + X_i X_j

    p_i² ∝ (kinetic hopping) → -½(X_i X_{i+1} + Y_i Y_{i+1})
         This is the XX model kinetic term (nearest-neighbor hopping).

Full qubit Hamiltonian:
    H_q = -J/2 Σ_{<i,j>} (X_i X_j + Y_i Y_j)       [kinetic hopping on hardware graph]
        + (ω₀²/2) Σ_i (I - Z_i)                      [on-site potential]
        + (1/N) Σ_{i<j} α_i α_j (Z_i Z_j + X_i X_j)  [anti-resonant coupling]

where <i,j> are nearest-neighbor pairs on the hardware coupling map.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

try:
    from qiskit.quantum_info import SparsePauliOp
except ImportError:
    SparsePauliOp = None  # Deferred — fails gracefully if qiskit not installed


def build_pendulum_hamiltonian(
    n_qubits: int,
    alpha_weights: np.ndarray,
    coupling_pairs: List[Tuple[int, int]],
    omega_0: float = 1.0,
    J_kinetic: float = 0.5,
    coupling_scale: float = 1.0,
) -> "SparsePauliOp":
    """Build the coupled-pendulum Hamiltonian as a SparsePauliOp.

    This is the exact Hamiltonian from the Golden Pendulum MTL paper,
    mapped to qubits with one qubit per oscillator.

    Args:
        n_qubits: Number of qubits (= number of coupled pendulums).
        alpha_weights: Anti-resonant weight vector, shape (n_qubits,).
            Must sum to 1.0. These are the α_i from the Hamiltonian.
        coupling_pairs: List of (i, j) qubit pairs that are physically
            connected on the hardware coupling map. Only these pairs get
            kinetic hopping terms (respects heavy-hex topology).
        omega_0: Natural frequency of each pendulum. Default 1.0.
        J_kinetic: Kinetic hopping strength. Default 0.5.
        coupling_scale: Overall coupling strength multiplier. Default 1.0.

    Returns:
        SparsePauliOp representing H_q.

    Raises:
        ValueError: If alpha_weights length != n_qubits.
    """
    if SparsePauliOp is None:
        raise ImportError("qiskit.quantum_info.SparsePauliOp required")

    if len(alpha_weights) != n_qubits:
        raise ValueError(
            f"alpha_weights length {len(alpha_weights)} != n_qubits {n_qubits}"
        )

    pauli_list = []
    coeff_list = []

    # ── Term 1: Kinetic hopping on hardware edges ─────────────────────────
    # H_kin = -(J/2) Σ_{<i,j>} (X_i X_j + Y_i Y_j)
    # This is the XY model — generates "momentum transport" between qubits.
    for (i, j) in coupling_pairs:
        if i >= n_qubits or j >= n_qubits:
            continue  # Skip edges outside our qubit set

        # XX term
        pauli_str = ["I"] * n_qubits
        pauli_str[i] = "X"
        pauli_str[j] = "X"
        pauli_list.append("".join(reversed(pauli_str)))  # Qiskit uses LSB
        coeff_list.append(-J_kinetic / 2.0)

        # YY term
        pauli_str = ["I"] * n_qubits
        pauli_str[i] = "Y"
        pauli_str[j] = "Y"
        pauli_list.append("".join(reversed(pauli_str)))
        coeff_list.append(-J_kinetic / 2.0)

    # ── Term 2: On-site potential ─────────────────────────────────────────
    # H_pot = (ω₀²/2) Σ_i (I - Z_i)
    # The (1 - cos θ) pendulum potential: minimum at θ=0 (Z=+1), maximum
    # at θ=π (Z=-1). Energy cost for each qubit to be in |1⟩ state.
    pot_coeff = omega_0 ** 2 / 2.0
    for i in range(n_qubits):
        # Identity contribution: (ω₀²/2) per qubit — constant energy offset
        # We skip this (just shifts eigenvalues uniformly)

        # -Z_i term: penalizes |1⟩ states
        pauli_str = ["I"] * n_qubits
        pauli_str[i] = "Z"
        pauli_list.append("".join(reversed(pauli_str)))
        coeff_list.append(-pot_coeff)

    # ── Term 3: Anti-resonant coupling ────────────────────────────────────
    # H_coup = (1/N) Σ_{i<j} α_i α_j (Z_i Z_j + X_i X_j)
    # This is WHERE the anti-resonant weights enter the quantum system.
    # Golden-ratio weights make the coupling strengths incommensurate,
    # preventing resonance between any pair of oscillators.
    N = float(n_qubits)
    for i in range(n_qubits):
        for j in range(i + 1, n_qubits):
            coupling_strength = coupling_scale * alpha_weights[i] * alpha_weights[j] / N

            # Skip negligibly small couplings (reduces circuit depth)
            if abs(coupling_strength) < 1e-8:
                continue

            # ZZ term: cos θ_i cos θ_j interaction
            pauli_str = ["I"] * n_qubits
            pauli_str[i] = "Z"
            pauli_str[j] = "Z"
            pauli_list.append("".join(reversed(pauli_str)))
            coeff_list.append(coupling_strength)

            # XX term: sin θ_i sin θ_j interaction
            pauli_str = ["I"] * n_qubits
            pauli_str[i] = "X"
            pauli_str[j] = "X"
            pauli_list.append("".join(reversed(pauli_str)))
            coeff_list.append(coupling_strength)

    # Build the SparsePauliOp and simplify
    hamiltonian = SparsePauliOp.from_list(
        list(zip(pauli_list, coeff_list))
    ).simplify()

    return hamiltonian


def decompose_for_measurement(
    hamiltonian: "SparsePauliOp",
) -> List[Tuple[str, complex]]:
    """Extract the Pauli terms for human-readable inspection.

    Returns:
        List of (pauli_string, coefficient) tuples, sorted by |coeff|.
    """
    terms = []
    for pauli, coeff in zip(hamiltonian.paulis, hamiltonian.coeffs):
        terms.append((str(pauli), complex(coeff)))
    terms.sort(key=lambda t: abs(t[1]), reverse=True)
    return terms


def estimate_trotter_depth(
    hamiltonian: "SparsePauliOp",
    time: float = 1.0,
    trotter_order: int = 1,
    target_error: float = 0.01,
) -> int:
    """Estimate the number of Trotter steps needed for time evolution.

    Uses the naive bound: error ≤ (||H||·t)² / (2·n_steps) for first-order
    Trotterization. This is conservative — actual error is often much lower.

    Args:
        hamiltonian: The SparsePauliOp Hamiltonian.
        time: Evolution time.
        trotter_order: 1 for Lie-Trotter, 2 for Suzuki-Trotter.
        target_error: Maximum acceptable Trotter error.

    Returns:
        Minimum number of Trotter steps.
    """
    # Spectral norm upper bound: sum of |coefficients|
    norm_bound = float(np.sum(np.abs(hamiltonian.coeffs)))
    if trotter_order == 1:
        # First-order: error ~ (||H||·t)² / (2·n)
        n_steps = int(np.ceil((norm_bound * time) ** 2 / (2.0 * target_error)))
    else:
        # Second-order: error ~ (||H||·t)³ / (12·n²)
        n_steps = int(np.ceil(
            ((norm_bound * time) ** 3 / (12.0 * target_error)) ** 0.5
        ))
    return max(n_steps, 1)
