"""Qiskit Runtime job submission for IBM Marrakesh.

Handles EstimatorV2 for Hamiltonian expectation values and SamplerV2 for
bitstring sampling, with support for both real hardware and FakeMarrakesh.

Follows the TriCameral.ai pattern:
    1. Transpile once per calibration epoch (optimization_level=2)
    2. Cache transpiled circuits by (circuit_type, n_qubits)
    3. Bind parameters with fresh values at submission time
    4. Let SabreLayout/SabreSwap handle qubit routing automatically

Key design decisions:
    - optimization_level=2: SabreLayout + SabreSwap routing. Level 3 is slower
      with diminishing returns for circuits under depth 100.
    - No manual initial_layout: The transpiler's built-in layout pass handles
      qubit selection correctly, respecting the backend's live calibration.
    - No error mitigation at circuit level: Our circuits are shallow (depth 20-60)
      and error mitigation overhead would increase depth, reducing fidelity.
    - Blocking execution: We call job.result() synchronously because the
      classical outer loop needs the result before the next iteration.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    """Result from a quantum job submission."""
    success: bool = True
    error: Optional[str] = None
    wall_time_s: float = 0.0

    # For EstimatorV2: expectation values
    expectation_values: Optional[np.ndarray] = None
    std_errors: Optional[np.ndarray] = None

    # For SamplerV2: measurement counts
    counts: Optional[Dict[str, int]] = None
    shots: int = 0


@dataclass
class TranspileCache:
    """Cache for transpiled circuits to avoid redundant transpilation."""
    _cache: Dict[str, Tuple] = field(default_factory=dict)
    _hits: int = 0
    _misses: int = 0

    def get(self, key: str):
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None

    def put(self, key: str, value):
        self._cache[key] = value

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0


class RuntimeManager:
    """Manages Qiskit Runtime job submission for the Quantum Golden Pendulum.

    Supports two execution modes:
        1. Real hardware (ibm_marrakesh via QiskitRuntimeService)
        2. Local simulation (FakeMarrakesh or AerSimulator)

    Usage:
        mgr = RuntimeManager(backend=backend)
        result = mgr.estimate(circuit, hamiltonian, params, values)
        result = mgr.sample(circuit, params, values, shots=4000)
    """

    def __init__(
        self,
        backend,
        optimization_level: int = 2,
        max_transpiled_depth: int = 300,
    ):
        """Initialize the runtime manager.

        Args:
            backend: IBM backend object (real or FakeMarrakesh).
            optimization_level: Transpilation optimization level (0-3).
            max_transpiled_depth: Maximum allowed transpiled circuit depth.
                Circuits exceeding this are rejected (produce pure noise).
        """
        self.backend = backend
        self.optimization_level = optimization_level
        self.max_transpiled_depth = max_transpiled_depth
        self._cache = TranspileCache()
        self._is_simulator = _is_simulator_backend(backend)

        logger.info(
            f"RuntimeManager: backend={backend.name}, "
            f"simulator={self._is_simulator}, opt_level={optimization_level}"
        )

    def transpile_circuit(
        self,
        circuit,
        cache_key: Optional[str] = None,
    ):
        """Transpile a parameterized circuit for the target backend.

        Uses caching: if the same circuit was already transpiled for this
        backend, returns the cached version. Invalidate cache when backend
        calibration changes.

        Args:
            circuit: Parameterized QuantumCircuit.
            cache_key: Optional cache key. If None, uses circuit.name.

        Returns:
            Transpiled QuantumCircuit.

        Raises:
            RuntimeError: If transpiled depth exceeds max_transpiled_depth.
        """
        from qiskit import transpile

        key = cache_key or circuit.name
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        t0 = time.monotonic()
        # For AerSimulator without a coupling map, skip backend-aware transpilation
        # (just do basic optimization). For real/fake IBM backends, use full routing.
        if self._is_simulator and not hasattr(self.backend, "coupling_map"):
            transpiled = transpile(
                circuit,
                optimization_level=min(self.optimization_level, 1),
            )
        else:
            transpiled = transpile(
                circuit,
                backend=self.backend,
                optimization_level=self.optimization_level,
                # Do NOT pass initial_layout — let SabreLayout choose optimal qubits
                # Do NOT pass coupling_map — it's read from the backend automatically
            )
        dt = time.monotonic() - t0

        depth = transpiled.depth()
        logger.info(
            f"Transpiled '{key}': depth={depth}, "
            f"gates={transpiled.size()}, time={dt:.2f}s"
        )

        if depth > self.max_transpiled_depth:
            raise RuntimeError(
                f"Transpiled depth {depth} exceeds limit {self.max_transpiled_depth}. "
                f"Circuit would produce pure noise on hardware. "
                f"Reduce n_qubits or n_var_layers."
            )

        self._cache.put(key, transpiled)
        return transpiled

    def estimate(
        self,
        circuit,
        observable,
        parameter_values: np.ndarray,
        precision: float = 0.01,
    ) -> JobResult:
        """Measure <psi(theta)|H|psi(theta)> using EstimatorV2.

        Handles the qubit-count mismatch that arises when transpilation maps
        an N-qubit circuit onto a larger backend. The observable is padded
        with identity operators to match the transpiled circuit width.

        Args:
            circuit: Transpiled parameterized circuit.
            observable: SparsePauliOp Hamiltonian (original N-qubit).
            parameter_values: 1D array of parameter values to bind.
            precision: Target precision for the estimate.

        Returns:
            JobResult with expectation_values and std_errors.
        """
        from qiskit.quantum_info import SparsePauliOp
        from qiskit_ibm_runtime import EstimatorV2

        t0 = time.monotonic()
        try:
            # Pad observable to match transpiled circuit width if needed
            circuit_qubits = circuit.num_qubits
            obs_qubits = observable.num_qubits
            if obs_qubits < circuit_qubits:
                # Pad each Pauli string with identity on the extra qubits
                padded_labels = []
                padded_coeffs = []
                pad_size = circuit_qubits - obs_qubits
                pad_str = "I" * pad_size
                for pauli, coeff in zip(observable.paulis, observable.coeffs):
                    # SparsePauliOp uses LSB ordering: pad on the LEFT (high qubits)
                    padded_labels.append(pad_str + str(pauli))
                    padded_coeffs.append(coeff)
                observable = SparsePauliOp.from_list(
                    list(zip(padded_labels, padded_coeffs))
                ).simplify()

            estimator = EstimatorV2(mode=self.backend)

            # EstimatorV2 expects a list of PUBs: (circuit, observable, params)
            job = estimator.run(
                [(circuit, observable, parameter_values)],
            )
            result = job.result()

            # Extract the single PUB result
            pub_result = result[0]
            evs = np.array([pub_result.data.evs])
            stds = np.array([pub_result.data.stds]) if hasattr(pub_result.data, "stds") else None

            return JobResult(
                success=True,
                wall_time_s=time.monotonic() - t0,
                expectation_values=evs,
                std_errors=stds,
            )

        except Exception as e:
            logger.error(f"Estimator job failed: {e}")
            return JobResult(
                success=False,
                error=str(e),
                wall_time_s=time.monotonic() - t0,
            )

    def sample(
        self,
        circuit,
        parameter_values: Optional[np.ndarray] = None,
        shots: int = 4000,
    ) -> JobResult:
        """Sample bitstrings from a (possibly parameterized) circuit.

        Automatically adds measurement gates if the circuit doesn't have them.

        Args:
            circuit: Transpiled circuit (parameterized or concrete).
            parameter_values: Parameter values to bind (None if circuit is concrete).
            shots: Number of measurement shots.

        Returns:
            JobResult with counts dict.
        """
        from qiskit import QuantumCircuit
        from qiskit_ibm_runtime import SamplerV2

        t0 = time.monotonic()
        try:
            sampler = SamplerV2(mode=self.backend)

            # Bind parameters if provided
            if parameter_values is not None and len(circuit.parameters) > 0:
                bound_circuit = circuit.assign_parameters(
                    dict(zip(circuit.parameters, parameter_values))
                )
            else:
                bound_circuit = circuit

            # Add measurement gates if the circuit doesn't have them
            if bound_circuit.num_clbits == 0:
                meas_circuit = bound_circuit.copy()
                meas_circuit.measure_all()
                bound_circuit = meas_circuit

            job = sampler.run([bound_circuit], shots=shots)
            result = job.result()

            # Extract counts — handle different DataBin attribute names
            pub_result = result[0]
            counts = None
            # Try common attribute names for measurement results
            for attr_name in ("meas", "c", "cr"):
                data_attr = getattr(pub_result.data, attr_name, None)
                if data_attr is not None:
                    counts = data_attr.get_counts()
                    break

            if counts is None:
                # Fallback: iterate over all data attributes
                for attr_name in dir(pub_result.data):
                    if attr_name.startswith("_"):
                        continue
                    data_attr = getattr(pub_result.data, attr_name, None)
                    if hasattr(data_attr, "get_counts"):
                        counts = data_attr.get_counts()
                        break

            if counts is None:
                raise RuntimeError(
                    f"Could not extract counts from result. "
                    f"DataBin attributes: {dir(pub_result.data)}"
                )

            return JobResult(
                success=True,
                wall_time_s=time.monotonic() - t0,
                counts=counts,
                shots=shots,
            )

        except Exception as e:
            logger.error(f"Sampler job failed: {e}")
            return JobResult(
                success=False,
                error=str(e),
                wall_time_s=time.monotonic() - t0,
            )

    def invalidate_cache(self):
        """Clear the transpile cache (call when calibration changes)."""
        self._cache = TranspileCache()
        logger.info("Transpile cache invalidated")


def _is_simulator_backend(backend) -> bool:
    """Check if a backend is a simulator (Fake or Aer)."""
    name = getattr(backend, "name", "")
    # FakeMarrakesh, FakeTorino, AerSimulator, etc.
    if "fake" in name.lower() or "aer" in name.lower() or "simulator" in name.lower():
        return True
    # Check for the Aer class
    cls_name = type(backend).__name__
    if "Fake" in cls_name or "Aer" in cls_name:
        return True
    return False


def connect_ibm_service(
    instance: str = "open-instance",
    backend_name: str = "ibm_marrakesh",
):
    """Connect to IBM Quantum and return the backend.

    Uses the same connection pattern as the working HHmL/TriCameral repos:
    QiskitRuntimeService(instance="open-instance") with the saved token.

    Args:
        instance: Service instance (default: "open-instance" per HHmL repos).
        backend_name: Name of the backend to use.

    Returns:
        IBM backend object.
    """
    from qiskit_ibm_runtime import QiskitRuntimeService

    logger.info(f"Connecting to IBM Quantum (instance={instance})...")
    service = QiskitRuntimeService(instance=instance)
    backend = service.backend(backend_name)

    status = backend.status()
    logger.info(
        f"Connected to {backend.name} "
        f"({backend.num_qubits} qubits, "
        f"status: {status.status_msg}, pending: {status.pending_jobs})"
    )

    return backend, service


def get_fake_backend(n_qubits: int = 0):
    """Get a simulator backend for local testing.

    For n_qubits <= 30, returns an AerSimulator with a depolarizing noise
    model (fast, memory-safe). For n_qubits > 30 or n_qubits=0, returns
    FakeMarrakesh (requires real hardware submission to actually run).

    The key issue: FakeMarrakesh transpiles ALL circuits to 156 qubits,
    which requires 2^156 memory to simulate. For local testing, we use
    AerSimulator with a realistic noise model instead.

    Args:
        n_qubits: Number of qubits in your circuit. If 0, returns
            FakeMarrakesh (caller is responsible for memory).
    """
    # For small circuits: use AerSimulator with noise model
    if n_qubits > 0 and n_qubits <= 30:
        try:
            from qiskit_aer import AerSimulator
            from qiskit_aer.noise import NoiseModel, depolarizing_error

            noise_model = NoiseModel()
            # Realistic noise rates for ibm_marrakesh Heron r2
            noise_model.add_all_qubit_quantum_error(
                depolarizing_error(0.001, 1), ["rx", "ry", "rz", "x", "h", "s", "sdg"]
            )
            noise_model.add_all_qubit_quantum_error(
                depolarizing_error(0.01, 2), ["cx", "ecr", "cz"]
            )

            sim = AerSimulator(noise_model=noise_model)
            sim.name = "aer_marrakesh_noise"
            logger.info(f"Using AerSimulator with Marrakesh-like noise (safe for {n_qubits}q)")
            return sim
        except ImportError:
            pass

    # Fallback: FakeMarrakesh (only works for real hardware submission)
    try:
        from qiskit_ibm_runtime.fake_provider import FakeMarrakesh
        return FakeMarrakesh()
    except ImportError:
        pass

    # Last resort: generic Aer with no noise
    try:
        from qiskit_aer import AerSimulator
        logger.warning("No fake IBM backend available, using noiseless AerSimulator")
        return AerSimulator()
    except ImportError:
        raise ImportError("Neither qiskit-aer nor qiskit-ibm-runtime fake provider available")
