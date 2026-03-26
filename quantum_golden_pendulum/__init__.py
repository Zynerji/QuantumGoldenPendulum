"""Quantum Golden Pendulum Chaos Engine.

A hybrid quantum-classical experiment that replaces the classical anti-resonant
weight optimization from GoldenPendulumMTL (Knopp, 2026) with quantum-native
phase rotations executed on the IBM Marrakesh 156-qubit Heron r2 processor.

The core hypothesis: anti-resonant (maximally irrational) weight sequences
stabilize the quantum simulation of a coupled-oscillator Hamiltonian better
than rational baselines, producing lower energy variance and faster convergence
to the 2φ-equilibrium phase.

Architecture:
    anti_resonant_weights.py  →  Weight generation (golden, bronze, cocktail, chaotic)
    hamiltonian.py            →  Coupled pendulum H → SparsePauliOp decomposition
    calibration.py            →  Live IBM Marrakesh calibration + qubit classification
    ansatz.py                 →  Hardware-efficient ansatz respecting heavy-hex topology
    runtime_job.py            →  Qiskit Runtime EstimatorV2/SamplerV2 submission
    optimizer.py              →  Classical outer loop with L1 tent regularizer
    conserved.py              →  Five conserved quantities (E₁, L₂, L₄, ω̄, φ̄)
    experiment.py             →  Main entry point orchestrating the full experiment
"""

__version__ = "0.1.0"
__author__ = "Christian Knopp"
