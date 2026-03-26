"""Hardware-efficient ansatz for IBM Marrakesh heavy-hex lattice.

The ansatz has two distinct parts:

    Layer 0 (FIXED): Anti-resonant weight encoding
        Ry(2π·α_k) on each qubit k, where α_k are the anti-resonant weights.
        This layer is NOT trainable — it encodes the physics of the problem
        directly into the quantum state. Changing the weight mode (golden,
        bronze, cocktail, chaotic) changes these fixed angles.

    Layers 1..L (TRAINABLE): Variational optimization layers
        Hardware-efficient brick-layer pattern:
        - Single-qubit: Ry(θ) + Rz(φ) on each qubit (2 params per qubit per layer)
        - Two-qubit: CX on hardware-connected pairs (respects coupling map)
        - Odd layers use even-indexed edges, even layers use odd-indexed edges
          (brick-layer pattern prevents all-to-all entanglement bottleneck)

    Total parameters: 2 * n_qubits * n_var_layers

The ansatz respects the heavy-hex topology by ONLY placing CX gates on
edges that exist in the hardware coupling map. No SWAP routing needed.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

try:
    from qiskit import QuantumCircuit
    from qiskit.circuit import Parameter, ParameterVector
except ImportError:
    QuantumCircuit = None
    Parameter = None
    ParameterVector = None

logger = logging.getLogger(__name__)


def build_pendulum_ansatz(
    n_qubits: int,
    fixed_angles: np.ndarray,
    coupling_edges: List[Tuple[int, int]],
    n_var_layers: int = 3,
    qubit_indices: Optional[List[int]] = None,
) -> Tuple["QuantumCircuit", "ParameterVector"]:
    """Build the full Quantum Golden Pendulum ansatz circuit.

    Args:
        n_qubits: Number of qubits in the circuit.
        fixed_angles: Anti-resonant angles θ_k = 2π·α_k, shape (n_qubits,).
            These are the FIXED first-layer rotations encoding the weight structure.
        coupling_edges: Hardware coupling map edges as (i, j) pairs.
            Only these pairs get CX gates. Must use LOCAL qubit indices (0..n-1),
            not physical qubit indices.
        n_var_layers: Number of trainable variational layers. Default 3.
        qubit_indices: Optional physical qubit indices for labeling. If None,
            uses 0..n_qubits-1.

    Returns:
        (circuit, parameters) tuple where parameters is the ParameterVector
        of all trainable angles.
    """
    if QuantumCircuit is None:
        raise ImportError("qiskit required")

    # Create parameter vector for all trainable angles
    n_params = 2 * n_qubits * n_var_layers
    params = ParameterVector("θ", n_params)

    qc = QuantumCircuit(n_qubits, name="GoldenPendulumAnsatz")

    # ── Layer 0: Fixed anti-resonant encoding ─────────────────────────────
    # This is the KEY innovation: the anti-resonant weights from the
    # GoldenPendulumMTL paper are burned directly into the quantum state.
    #
    # Ry(2π·α_k) rotates qubit k to an angle proportional to its weight.
    # Because the α_k have irrational ratios (golden, bronze, etc.), no two
    # qubits will ever be at a rational multiple of each other's angle.
    # This prevents resonance in the subsequent entangling layers.
    qc.barrier(label="anti-resonant encoding")
    for k in range(n_qubits):
        qc.ry(float(fixed_angles[k]), k)

    # Split coupling edges into two sets for brick-layer pattern
    edges_even = [(i, j) for idx, (i, j) in enumerate(coupling_edges) if idx % 2 == 0]
    edges_odd = [(i, j) for idx, (i, j) in enumerate(coupling_edges) if idx % 2 == 1]

    # ── Layers 1..L: Trainable variational layers ─────────────────────────
    param_idx = 0
    for layer in range(n_var_layers):
        qc.barrier(label=f"var_layer_{layer}")

        # Single-qubit rotations: Ry + Rz per qubit
        for k in range(n_qubits):
            qc.ry(params[param_idx], k)
            param_idx += 1
            qc.rz(params[param_idx], k)
            param_idx += 1

        # Two-qubit entangling: CX on hardware edges (brick-layer)
        # Odd layers use even edges, even layers use odd edges
        edge_set = edges_even if layer % 2 == 0 else edges_odd
        for (i, j) in edge_set:
            if i < n_qubits and j < n_qubits:
                qc.cx(i, j)

    assert param_idx == n_params, f"Parameter count mismatch: {param_idx} != {n_params}"

    logger.info(
        f"Ansatz: {n_qubits}q, {n_var_layers} var layers, "
        f"{n_params} trainable params, depth {qc.depth()}"
    )

    return qc, params


def build_quantum_logistic_circuit(
    n_sample_qubits: int = 8,
    n_iterations: int = 3,
) -> "QuantumCircuit":
    """Build the auxiliary circuit for quantum chaotic feedback.

    This is the "unhinged" part: a small circuit that implements a
    quantum analog of the logistic map x → 4x(1-x) using controlled
    rotations. The measurement outcomes, after burn-in, produce
    chaotic samples that are fed back as weight perturbations.

    The quantum logistic map uses the transformation:
        |x⟩ → Ry(4·arcsin(√x)·(1-x)) |x⟩

    approximated by a cascade of controlled-Ry gates.

    Args:
        n_sample_qubits: Number of qubits to sample chaotic values from.
        n_iterations: Number of logistic map iterations (depth).

    Returns:
        QuantumCircuit with n_sample_qubits measured outputs.
    """
    qc = QuantumCircuit(n_sample_qubits, n_sample_qubits, name="QuantumLogistic")

    # Initialize with superposition (seed state)
    # The angle 2·arcsin(1/√φ) ≈ 1.826 rad encodes the golden seed 1/φ
    golden_seed_angle = 2.0 * np.arcsin(1.0 / np.sqrt((1.0 + np.sqrt(5.0)) / 2.0))
    for q in range(n_sample_qubits):
        qc.ry(golden_seed_angle, q)

    # Iterate the quantum logistic map
    for iteration in range(n_iterations):
        # Pairwise controlled rotations simulate the nonlinear map
        for q in range(n_sample_qubits - 1):
            # Controlled-Ry with angle that depends on iteration
            # This creates the x(1-x) nonlinearity via entanglement
            angle = np.pi / (iteration + 2)  # Decreasing angles → convergence
            qc.cry(angle, q, (q + 1) % n_sample_qubits)

        # Self-rotation (the 4x scaling factor)
        for q in range(n_sample_qubits):
            qc.ry(np.pi / 4, q)  # Quarter-turn approximation

    # Measure all qubits
    qc.measure(range(n_sample_qubits), range(n_sample_qubits))

    return qc


def counts_to_chaotic_weights(
    counts: dict,
    n_weights: int,
    floor: float = 0.01,
) -> np.ndarray:
    """Convert quantum measurement counts to chaotic weight perturbations.

    Takes the bitstring distribution from the quantum logistic circuit and
    maps it to a weight vector on the simplex. The quantum randomness
    ensures true unpredictability (not pseudo-random), while the logistic
    circuit structure biases the distribution toward the arcsine measure
    (the invariant distribution of the classical logistic map at r=4).

    Args:
        counts: Measurement counts dict from Qiskit (e.g., {"010": 145}).
        n_weights: Number of weights to produce.
        floor: Minimum weight per entry.

    Returns:
        numpy array of shape (n_weights,) summing to 1.0.
    """
    total_shots = sum(counts.values())
    if total_shots == 0:
        return np.ones(n_weights) / n_weights

    # Convert bitstring frequencies to a probability distribution
    # Use the top-n_weights most frequent outcomes
    sorted_outcomes = sorted(counts.items(), key=lambda x: -x[1])

    raw = []
    for i in range(n_weights):
        if i < len(sorted_outcomes):
            raw.append(max(sorted_outcomes[i][1] / total_shots, floor))
        else:
            raw.append(floor)

    arr = np.array(raw)
    return arr / arr.sum()
