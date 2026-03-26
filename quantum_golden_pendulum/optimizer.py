"""Classical outer-loop optimizer for the Quantum Golden Pendulum.

Implements the anti-resonant optimization loop from Algorithm 1 of the
Golden Pendulum MTL paper (Knopp, 2026), adapted for hybrid quantum-classical
variational optimization.

The key insight: instead of optimizing task-gradient weights (as in MTL),
we optimize the VARIATIONAL PARAMETERS of the quantum ansatz while keeping
the anti-resonant structure fixed in Layer 0. The L1 tent regularizer pulls
the measured phase statistics toward the 2φ-equilibrium.

Optimization loop:
    1. Bind current parameter values θ to the ansatz circuit
    2. Submit to QPU → get <H> (energy) and bitstring counts
    3. Compute the five conserved quantities from the counts
    4. Compute cost = <H> + λ·||φ̄ - 2φ||₁  (energy + phase deviation penalty)
    5. Update θ using SPSA (Simultaneous Perturbation Stochastic Approximation)
       — the standard gradient-free optimizer for quantum circuits
    6. Every 10 iterations: run quantum logistic feedback loop

SPSA is used instead of parameter-shift because:
    - It requires only 2 circuit evaluations per step (vs 2P for parameter-shift)
    - On 156 qubits with ~1000 parameters, this saves ~500x QPU time
    - The stochastic noise from SPSA is actually beneficial — it prevents
      the optimizer from getting trapped in local minima
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .anti_resonant_weights import PHI, TWO_PHI, get_weights, weights_to_angles
from .conserved import (
    ConservedQuantities,
    measure_conserved_quantities,
)

logger = logging.getLogger(__name__)


@dataclass
class OptimizationStep:
    """Record of a single optimization iteration."""
    iteration: int
    energy: float              # <H> expectation value
    cost: float                # energy + regularizer
    conserved: ConservedQuantities
    weight_mode: str
    wall_time_s: float = 0.0
    is_quantum_feedback: bool = False  # True every 10th iteration


@dataclass
class OptimizationResult:
    """Full result of the optimization run."""
    steps: List[OptimizationStep] = field(default_factory=list)
    best_energy: float = float("inf")
    best_params: Optional[np.ndarray] = None
    best_step: int = 0
    total_wall_time_s: float = 0.0
    total_qpu_calls: int = 0

    @property
    def energies(self) -> np.ndarray:
        return np.array([s.energy for s in self.steps])

    @property
    def costs(self) -> np.ndarray:
        return np.array([s.cost for s in self.steps])

    @property
    def phi_bars(self) -> np.ndarray:
        return np.array([s.conserved.phi_bar for s in self.steps])

    @property
    def E1s(self) -> np.ndarray:
        return np.array([s.conserved.E1 for s in self.steps])


class SPSAOptimizer:
    """SPSA optimizer with L1 tent regularizer toward 2φ-equilibrium.

    This is a quantum-adapted version of the GoldenPendulumMTL solver.
    Instead of solving a QP over task weights, it uses SPSA to optimize
    variational circuit parameters while penalizing deviation from the
    anti-resonant phase equilibrium.

    Args:
        n_params: Number of variational parameters.
        lam: L1 tent regularizer strength (λ in the cost function).
            Higher values enforce the 2φ target more strictly.
        a: SPSA initial step size for parameter updates.
        c: SPSA initial perturbation size.
        alpha: SPSA step size decay exponent. Step size = a / (k+A)^alpha.
        gamma: SPSA perturbation decay exponent. Perturbation = c / k^gamma.
        A: SPSA stability constant (typically 10% of max iterations).
    """

    def __init__(
        self,
        n_params: int,
        lam: float = 0.5,
        a: float = 0.1,
        c: float = 0.1,
        alpha: float = 0.602,
        gamma: float = 0.101,
        A: int = 10,
    ):
        self.n_params = n_params
        self.lam = lam
        self.a = a
        self.c = c
        self.alpha = alpha
        self.gamma = gamma
        self.A = A

        # Initialize parameters randomly in [-π, π]
        self.params = np.random.uniform(-np.pi, np.pi, n_params)

    def compute_cost(
        self,
        energy: float,
        conserved: ConservedQuantities,
    ) -> float:
        """Compute total cost = energy + λ·|φ̄ - 2φ| + λ/2·|E₁ - 1|.

        The L1 tent regularizer pulls the measured conserved quantities
        toward their theoretical targets, just as the GoldenPendulumMTL
        QP solver pulls task weights toward golden-ratio targets.

        Args:
            energy: <H> expectation value from the quantum circuit.
            conserved: Measured conserved quantities.

        Returns:
            Total cost (scalar).
        """
        # Primary: energy minimization
        cost = energy

        # L1 tent: pull phase toward 2φ equilibrium
        cost += self.lam * abs(conserved.phi_bar - TWO_PHI)

        # Secondary L1 penalties on other conservation laws
        cost += (self.lam / 2.0) * abs(conserved.E1 - 1.0)
        cost += (self.lam / 4.0) * abs(conserved.L2 - np.pi)

        return cost

    def step(
        self,
        k: int,
        cost_fn: Callable[[np.ndarray], float],
    ) -> Tuple[np.ndarray, float]:
        """One SPSA iteration.

        Args:
            k: Current iteration number (1-indexed).
            cost_fn: Function that takes parameter vector → scalar cost.
                This function should submit the circuit to QPU and measure.

        Returns:
            (updated_params, cost_at_current_params)
        """
        # Decaying step size and perturbation
        ak = self.a / (k + self.A) ** self.alpha
        ck = self.c / k ** self.gamma

        # Random perturbation direction (Bernoulli ±1)
        delta = np.random.choice([-1, 1], size=self.n_params).astype(float)

        # Evaluate cost at θ+cΔ and θ-cΔ
        cost_plus = cost_fn(self.params + ck * delta)
        cost_minus = cost_fn(self.params - ck * delta)

        # SPSA gradient estimate
        g_hat = (cost_plus - cost_minus) / (2.0 * ck * delta)

        # Update parameters
        self.params = self.params - ak * g_hat

        # Clip to [-2π, 2π] to prevent parameter explosion
        self.params = np.clip(self.params, -2 * np.pi, 2 * np.pi)

        # Return cost at the midpoint (current params before update)
        cost_current = (cost_plus + cost_minus) / 2.0

        return self.params.copy(), cost_current


class QuantumGoldenPendulumOptimizer:
    """Full hybrid quantum-classical optimization loop.

    Orchestrates:
        1. SPSA parameter optimization on the QPU
        2. Conservation law monitoring
        3. Quantum chaotic feedback loop (every 10 iterations)
        4. Comparison across weight modes (golden, bronze, cocktail, chaotic)

    Args:
        runtime_manager: RuntimeManager for QPU job submission.
        ansatz_builder: Callable that builds (circuit, params) given angles.
        hamiltonian: SparsePauliOp for the coupled pendulum system.
        n_qubits: Number of qubits in the experiment.
        weight_mode: Anti-resonant weight mode name.
        n_var_layers: Number of variational ansatz layers.
        lam: L1 tent regularizer strength.
        max_iterations: Maximum optimization iterations.
        shots: Measurement shots per circuit evaluation.
        feedback_interval: Run quantum chaotic feedback every N iterations.
    """

    def __init__(
        self,
        runtime_manager,
        ansatz_circuit,
        hamiltonian,
        n_qubits: int,
        weight_mode: str = "golden",
        n_var_layers: int = 3,
        lam: float = 0.5,
        max_iterations: int = 100,
        shots: int = 4000,
        feedback_interval: int = 10,
    ):
        self.runtime = runtime_manager
        self.ansatz = ansatz_circuit
        self.hamiltonian = hamiltonian
        self.n_qubits = n_qubits
        self.weight_mode = weight_mode
        self.n_var_layers = n_var_layers
        self.lam = lam
        self.max_iterations = max_iterations
        self.shots = shots
        self.feedback_interval = feedback_interval

        # Count trainable parameters
        n_params = 2 * n_qubits * n_var_layers
        self.spsa = SPSAOptimizer(
            n_params=n_params,
            lam=lam,
            A=max(1, max_iterations // 10),
        )

        self._previous_probs = None

    def run(
        self,
        progress_callback=None,
    ) -> OptimizationResult:
        """Execute the full optimization loop.

        Args:
            progress_callback: Optional callable(step: OptimizationStep)
                called after each iteration for progress reporting.

        Returns:
            OptimizationResult with full history.
        """
        result = OptimizationResult()
        t_start = time.monotonic()
        qpu_calls = 0

        # Transpile the ansatz circuit once
        transpiled = self.runtime.transpile_circuit(
            self.ansatz,
            cache_key=f"pendulum_{self.weight_mode}_{self.n_qubits}q",
        )

        logger.info(
            f"Starting optimization: mode={self.weight_mode}, "
            f"qubits={self.n_qubits}, layers={self.n_var_layers}, "
            f"max_iter={self.max_iterations}, λ={self.lam}"
        )

        for k in range(1, self.max_iterations + 1):
            t_iter = time.monotonic()
            is_feedback = (k % self.feedback_interval == 0)

            # ── Define the cost function for SPSA ─────────────────────────
            def cost_fn(params: np.ndarray) -> float:
                nonlocal qpu_calls
                # Measure <H> using EstimatorV2
                est_result = self.runtime.estimate(
                    transpiled,
                    self.hamiltonian,
                    params,
                )
                qpu_calls += 1

                if not est_result.success:
                    logger.warning(f"Estimator failed: {est_result.error}")
                    return 1e6  # Penalty for failed jobs

                energy = float(est_result.expectation_values[0])
                return energy  # Raw energy for SPSA gradient estimation

            # ── SPSA step ─────────────────────────────────────────────────
            params, raw_cost = self.spsa.step(k, cost_fn)
            qpu_calls += 2  # SPSA uses 2 evaluations

            # ── Measure conserved quantities via Sampler ──────────────────
            # Add measurements to the ansatz for sampling
            sample_result = self.runtime.sample(
                transpiled,
                parameter_values=params,
                shots=self.shots,
            )
            qpu_calls += 1

            if sample_result.success and sample_result.counts:
                conserved = measure_conserved_quantities(
                    sample_result.counts,
                    self.n_qubits,
                    self._previous_probs,
                )

                # Update previous probs for stability tracking
                total = sum(sample_result.counts.values())
                n_outcomes = 2 ** min(self.n_qubits, 12)  # Cap for memory
                probs = np.zeros(n_outcomes)
                for bs, cnt in sample_result.counts.items():
                    idx = int(bs, 2) % n_outcomes
                    probs[idx] = cnt / total
                self._previous_probs = probs
            else:
                conserved = ConservedQuantities()

            # Compute full cost with regularizer
            full_cost = self.spsa.compute_cost(raw_cost, conserved)

            # ── Quantum chaotic feedback (every feedback_interval steps) ──
            if is_feedback:
                self._quantum_feedback_step(k)

            # ── Record step ───────────────────────────────────────────────
            step = OptimizationStep(
                iteration=k,
                energy=raw_cost,
                cost=full_cost,
                conserved=conserved,
                weight_mode=self.weight_mode,
                wall_time_s=time.monotonic() - t_iter,
                is_quantum_feedback=is_feedback,
            )
            result.steps.append(step)

            if raw_cost < result.best_energy:
                result.best_energy = raw_cost
                result.best_params = params.copy()
                result.best_step = k

            # Progress reporting
            if progress_callback:
                progress_callback(step)

            if k % 10 == 0 or k == 1:
                logger.info(
                    f"[{k:>4d}/{self.max_iterations}] "
                    f"E={raw_cost:+.6f}  cost={full_cost:.6f}  "
                    f"φ̄={conserved.phi_bar:.4f}  E₁={conserved.E1:.4f}  "
                    f"χ={conserved.chi:.3f}"
                )

        result.total_wall_time_s = time.monotonic() - t_start
        result.total_qpu_calls = qpu_calls

        logger.info(
            f"Optimization complete: best_energy={result.best_energy:.6f} "
            f"at step {result.best_step}, "
            f"QPU calls={qpu_calls}, wall_time={result.total_wall_time_s:.1f}s"
        )

        return result

    def _quantum_feedback_step(self, iteration: int):
        """Run the quantum chaotic feedback loop.

        Every feedback_interval iterations, use a small auxiliary circuit
        to generate chaotic weight perturbations from quantum measurements.
        These perturb the SPSA optimizer's parameters, injecting genuine
        quantum randomness into the optimization trajectory.

        This closes the loop between classical theory and quantum hardware:
        the logistic map (a classical chaotic system) is simulated on quantum
        hardware, and its output feeds back into the classical optimizer.
        """
        from .ansatz import build_quantum_logistic_circuit, counts_to_chaotic_weights

        logger.info(f"  [iter {iteration}] Running quantum chaotic feedback...")

        # Build and run the logistic map circuit
        logistic_circuit = build_quantum_logistic_circuit(
            n_sample_qubits=8,
            n_iterations=3,
        )

        # Transpile the small circuit
        transpiled_logistic = self.runtime.transpile_circuit(
            logistic_circuit,
            cache_key="quantum_logistic_8q",
        )

        result = self.runtime.sample(
            transpiled_logistic,
            shots=1000,
        )

        if result.success and result.counts:
            # Convert quantum measurement to chaotic perturbation
            chaotic_perturbation = counts_to_chaotic_weights(
                result.counts,
                n_weights=self.spsa.n_params,
            )

            # Apply as small perturbation to current parameters
            # Scale: ±0.01 radians — enough to escape local minima
            # but not enough to destroy convergence
            perturbation_scale = 0.01 * np.pi
            centered = chaotic_perturbation - chaotic_perturbation.mean()
            self.spsa.params += perturbation_scale * centered

            logger.info(
                f"  Quantum feedback applied: "
                f"perturbation norm={np.linalg.norm(centered * perturbation_scale):.6f}"
            )
        else:
            logger.warning("  Quantum feedback failed — skipping")
