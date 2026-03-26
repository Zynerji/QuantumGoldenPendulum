#!/usr/bin/env python3
"""Quantum Golden Pendulum Chaos Engine — Main Experiment Runner.

Runs the full comparative experiment: measures <H>, energy variance, phase
convergence (φ̄→2φ), and all five conserved quantities across multiple
anti-resonant weight modes AND rational baselines.

The experiment demonstrates that anti-resonant (maximally irrational) weight
sequences stabilize quantum simulation of the coupled-oscillator Hamiltonian
better than rational baselines, producing:
    1. Lower ground-state energy estimates
    2. Faster convergence to the 2φ-equilibrium phase
    3. Better conservation law adherence (E₁→1, L₂→π, etc.)
    4. Lower energy variance across measurement shots

Usage:
    # Local simulation (FakeMarrakesh)
    python -m quantum_golden_pendulum.experiment --simulate --n-qubits 20

    # Real IBM Marrakesh hardware
    python -m quantum_golden_pendulum.experiment --n-qubits 156 --max-iter 50

    # Quick test with specific mode
    python -m quantum_golden_pendulum.experiment --simulate --n-qubits 8 --modes golden --max-iter 10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np

from .anti_resonant_weights import get_weights, rational_baseline_weights, weights_to_angles
from .calibration import pull_calibration, select_qubit_subset, get_fallback_calibration
from .hamiltonian import build_pendulum_hamiltonian
from .ansatz import build_pendulum_ansatz
from .optimizer import QuantumGoldenPendulumOptimizer, OptimizationResult
from .runtime_job import RuntimeManager, get_fake_backend, connect_ibm_service

logger = logging.getLogger(__name__)

# ─── Default experiment configuration ─────────────────────────────────────────
DEFAULT_MODES = ["golden", "bronze", "cocktail", "chaotic_logistic"]
DEFAULT_BASELINES = ["uniform", "harmonic"]
DEFAULT_N_QUBITS = 20          # Conservative default for testing
DEFAULT_N_VAR_LAYERS = 3
DEFAULT_MAX_ITER = 50
DEFAULT_SHOTS = 4000
DEFAULT_LAM = 0.5


def run_single_mode(
    mode_name: str,
    weights: np.ndarray,
    runtime: RuntimeManager,
    coupling_edges: List,
    n_qubits: int,
    n_var_layers: int,
    max_iterations: int,
    shots: int,
    lam: float,
) -> OptimizationResult:
    """Run the optimization loop for a single weight mode.

    Args:
        mode_name: Human-readable name for logging.
        weights: Anti-resonant weight vector, shape (n_qubits,).
        runtime: RuntimeManager for QPU submission.
        coupling_edges: Hardware coupling map edges (local indices).
        n_qubits: Number of qubits.
        n_var_layers: Variational layers.
        max_iterations: SPSA iterations.
        shots: Measurement shots per evaluation.
        lam: L1 tent regularizer strength.

    Returns:
        OptimizationResult with full history.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Mode: {mode_name}")
    logger.info(f"Weights (first 8): {weights[:8].round(4)}")
    logger.info(f"Weight entropy: {-np.sum(weights * np.log(weights + 1e-10)):.4f}")
    logger.info(f"{'='*60}")

    # Convert weights to fixed rotation angles
    fixed_angles = weights_to_angles(weights)

    # Build the ansatz circuit
    ansatz, params = build_pendulum_ansatz(
        n_qubits=n_qubits,
        fixed_angles=fixed_angles,
        coupling_edges=coupling_edges,
        n_var_layers=n_var_layers,
    )

    # Build the Hamiltonian with these specific anti-resonant weights
    hamiltonian = build_pendulum_hamiltonian(
        n_qubits=n_qubits,
        alpha_weights=weights,
        coupling_pairs=coupling_edges,
    )

    # Run optimization
    optimizer = QuantumGoldenPendulumOptimizer(
        runtime_manager=runtime,
        ansatz_circuit=ansatz,
        hamiltonian=hamiltonian,
        n_qubits=n_qubits,
        weight_mode=mode_name,
        n_var_layers=n_var_layers,
        lam=lam,
        max_iterations=max_iterations,
        shots=shots,
    )

    def progress_cb(step):
        if step.iteration % 10 == 0:
            print(
                f"  [{mode_name:>20s}] iter {step.iteration:>4d}: "
                f"E={step.energy:+.4f}  φ̄={step.conserved.phi_bar:.4f}  "
                f"E₁={step.conserved.E1:.4f}  χ={step.conserved.chi:.3f}"
            )

    result = optimizer.run(progress_callback=progress_cb)
    return result


def run_experiment(args: argparse.Namespace) -> Dict[str, OptimizationResult]:
    """Run the full comparative experiment across all modes.

    Returns:
        Dict mapping mode_name → OptimizationResult.
    """
    t_start = time.monotonic()

    # ── Backend setup ─────────────────────────────────────────────────────
    if args.simulate:
        logger.info("Using AerSimulator with Marrakesh noise for local simulation")
        backend = get_fake_backend(n_qubits=args.n_qubits)
    else:
        logger.info(f"Connecting to {args.backend}...")
        backend, _service = connect_ibm_service(
            backend_name=args.backend,
            instance=args.instance,
        )

    runtime = RuntimeManager(
        backend=backend,
        optimization_level=2,
    )

    # ── Calibration ───────────────────────────────────────────────────────
    logger.info("Pulling calibration data...")
    try:
        cal = pull_calibration(
            backend,
            save_path=Path(args.output_dir) / "calibration.json",
        )
    except Exception as e:
        logger.warning(f"Live calibration failed ({e}), using fallback")
        cal = get_fallback_calibration(backend.num_qubits)

    # Select best qubits
    n_qubits = args.n_qubits
    if n_qubits > len(cal.good_qubits):
        logger.warning(
            f"Requested {n_qubits} qubits but only {len(cal.good_qubits)} good. "
            f"Reducing to {len(cal.good_qubits)}."
        )
        n_qubits = len(cal.good_qubits)

    selected_qubits, selected_edges = select_qubit_subset(cal, n_qubits)

    # Remap edges to local indices (0..n_qubits-1)
    qubit_to_local = {q: i for i, q in enumerate(selected_qubits)}
    local_edges = [
        (qubit_to_local[i], qubit_to_local[j])
        for (i, j) in selected_edges
        if i in qubit_to_local and j in qubit_to_local
    ]

    logger.info(
        f"Selected {n_qubits} qubits with {len(local_edges)} edges "
        f"(physical qubits: {selected_qubits[:10]}...)"
    )

    # ── Run each weight mode ──────────────────────────────────────────────
    results: Dict[str, OptimizationResult] = {}

    # Anti-resonant modes
    for mode in args.modes:
        weights = get_weights(mode, n_qubits)
        result = run_single_mode(
            mode_name=mode,
            weights=weights,
            runtime=runtime,
            coupling_edges=local_edges,
            n_qubits=n_qubits,
            n_var_layers=args.n_var_layers,
            max_iterations=args.max_iter,
            shots=args.shots,
            lam=args.lam,
        )
        results[mode] = result

    # Rational baselines
    for baseline in args.baselines:
        weights = rational_baseline_weights(n_qubits, mode=baseline)
        result = run_single_mode(
            mode_name=f"baseline_{baseline}",
            weights=weights,
            runtime=runtime,
            coupling_edges=local_edges,
            n_qubits=n_qubits,
            n_var_layers=args.n_var_layers,
            max_iterations=args.max_iter,
            shots=args.shots,
            lam=args.lam,
        )
        results[f"baseline_{baseline}"] = result

    # ── Save results ──────────────────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = _build_summary(results, n_qubits, args)
    summary_path = output_dir / "experiment_results.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info(f"Results saved to {summary_path}")

    # ── Print comparison table ────────────────────────────────────────────
    _print_comparison_table(results)

    total_time = time.monotonic() - t_start
    total_qpu = sum(r.total_qpu_calls for r in results.values())
    logger.info(
        f"\nExperiment complete: {total_time:.1f}s wall time, "
        f"{total_qpu} total QPU calls"
    )

    return results


def _build_summary(
    results: Dict[str, OptimizationResult],
    n_qubits: int,
    args: argparse.Namespace,
) -> dict:
    """Build a JSON-serializable summary of the experiment."""
    summary = {
        "experiment": "Quantum Golden Pendulum Chaos Engine",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "n_qubits": n_qubits,
            "n_var_layers": args.n_var_layers,
            "max_iterations": args.max_iter,
            "shots": args.shots,
            "lam": args.lam,
            "simulate": args.simulate,
            "backend": args.backend,
        },
        "results": {},
    }

    for mode_name, result in results.items():
        final = result.steps[-1] if result.steps else None
        summary["results"][mode_name] = {
            "best_energy": float(result.best_energy),
            "best_step": result.best_step,
            "total_qpu_calls": result.total_qpu_calls,
            "wall_time_s": round(result.total_wall_time_s, 2),
            "final_conserved": {
                "E1": round(final.conserved.E1, 6) if final else None,
                "L2": round(final.conserved.L2, 6) if final else None,
                "L4": round(final.conserved.L4, 6) if final else None,
                "omega_bar": round(final.conserved.omega_bar, 6) if final else None,
                "phi_bar": round(final.conserved.phi_bar, 6) if final else None,
                "total_deviation": round(final.conserved.total_deviation(), 6) if final else None,
            },
            "energy_trajectory": [
                round(float(e), 6) for e in result.energies[-10:]
            ],
        }

    return summary


def _print_comparison_table(results: Dict[str, OptimizationResult]):
    """Print a formatted comparison table of all modes."""
    print("\n" + "=" * 90)
    print("QUANTUM GOLDEN PENDULUM — COMPARISON TABLE")
    print("=" * 90)
    print(f"{'Mode':<22s} {'Best E':>10s} {'Step':>5s} {'φ̄':>8s} {'E₁':>8s} "
          f"{'L₂':>8s} {'Σ|dev|':>8s} {'QPU':>6s}")
    print("-" * 90)

    for mode_name, result in sorted(results.items()):
        final = result.steps[-1] if result.steps else None
        if final:
            is_baseline = mode_name.startswith("baseline_")
            marker = "  ←BASELINE" if is_baseline else ""
            print(
                f"{mode_name:<22s} "
                f"{result.best_energy:>+10.4f} "
                f"{result.best_step:>5d} "
                f"{final.conserved.phi_bar:>8.4f} "
                f"{final.conserved.E1:>8.4f} "
                f"{final.conserved.L2:>8.4f} "
                f"{final.conserved.total_deviation():>8.4f} "
                f"{result.total_qpu_calls:>6d}"
                f"{marker}"
            )

    print("-" * 90)
    print(f"Targets:{'':>33s} {'2φ≈3.236':>8s} {'1.0':>8s} {'π≈3.142':>8s}")
    print("=" * 90)

    # Winner determination
    anti_res = {k: v for k, v in results.items() if not k.startswith("baseline_")}
    baselines = {k: v for k, v in results.items() if k.startswith("baseline_")}

    if anti_res and baselines:
        best_ar = min(anti_res.items(), key=lambda x: x[1].best_energy)
        best_bl = min(baselines.items(), key=lambda x: x[1].best_energy)

        improvement = best_bl[1].best_energy - best_ar[1].best_energy
        print(f"\nBest anti-resonant: {best_ar[0]} (E={best_ar[1].best_energy:+.6f})")
        print(f"Best baseline:      {best_bl[0]} (E={best_bl[1].best_energy:+.6f})")

        if improvement > 0:
            print(f"Anti-resonant advantage: {improvement:.6f} lower energy")
        else:
            print(f"Baseline advantage: {-improvement:.6f} lower energy")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Quantum Golden Pendulum Chaos Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--simulate", action="store_true",
        help="Use FakeMarrakesh for local simulation (no QPU cost)",
    )
    parser.add_argument(
        "--backend", default="ibm_marrakesh",
        help="IBM backend name for real hardware runs",
    )
    parser.add_argument(
        "--instance", default="ibm-q/open/main",
        help="IBM Quantum service instance",
    )
    parser.add_argument(
        "--n-qubits", type=int, default=DEFAULT_N_QUBITS,
        help="Number of qubits to use",
    )
    parser.add_argument(
        "--n-var-layers", type=int, default=DEFAULT_N_VAR_LAYERS,
        help="Number of trainable variational layers in the ansatz",
    )
    parser.add_argument(
        "--max-iter", type=int, default=DEFAULT_MAX_ITER,
        help="Maximum SPSA optimization iterations per mode",
    )
    parser.add_argument(
        "--shots", type=int, default=DEFAULT_SHOTS,
        help="Measurement shots per circuit evaluation",
    )
    parser.add_argument(
        "--lam", type=float, default=DEFAULT_LAM,
        help="L1 tent regularizer strength (lambda)",
    )
    parser.add_argument(
        "--modes", nargs="+", default=DEFAULT_MODES,
        help="Anti-resonant weight modes to test",
    )
    parser.add_argument(
        "--baselines", nargs="+", default=DEFAULT_BASELINES,
        help="Rational baseline modes for comparison",
    )
    parser.add_argument(
        "--output-dir", default="results",
        help="Directory for output files",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Run the experiment
    results = run_experiment(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
