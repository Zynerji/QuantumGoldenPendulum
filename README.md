# Quantum Golden Pendulum Chaos Engine

A hybrid quantum-classical experiment demonstrating that **anti-resonant weight sequences** (golden ratio, metallic means, transcendental cocktails, chaotic logistic maps) stabilize quantum simulation of coupled-oscillator Hamiltonians better than rational baselines.

Runs on the **IBM Marrakesh 156-qubit Heron r2 processor** or locally on FakeMarrakesh.

## Core Hypothesis

Task gradients in multi-task learning are modeled as coupled wave oscillators (Knopp, 2026). We replace the classical anti-resonant weights with **quantum-native phase rotations** on real QPU hardware. The experiment measures whether irrational weight spacing prevents resonance-induced decoherence, producing:

1. Lower ground-state energy estimates
2. Faster convergence to the 2phi-equilibrium phase
3. Better conservation law adherence (E1->1, L2->pi, L4->sqrt(e))
4. Lower energy variance across measurement shots

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Local simulation (no QPU cost)
python -m quantum_golden_pendulum.experiment --simulate --n-qubits 20 --max-iter 30

# Real IBM Marrakesh (requires IBM Quantum account)
python -m quantum_golden_pendulum.experiment --n-qubits 156 --max-iter 50

# Specific modes only
python -m quantum_golden_pendulum.experiment --simulate --modes golden chaotic_logistic --baselines uniform
```

## IBM Quantum Setup

1. Create an account at [quantum.ibm.com](https://quantum.ibm.com)
2. Save your API token:
```python
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(channel="ibm_quantum", token="YOUR_TOKEN")
```
3. Run on real hardware:
```bash
python -m quantum_golden_pendulum.experiment --backend ibm_marrakesh --n-qubits 156
```

## Architecture

```
quantum_golden_pendulum/
  __init__.py              # Package metadata
  anti_resonant_weights.py # 11 weight families (golden, bronze, cocktail, chaotic, ...)
  hamiltonian.py           # Coupled pendulum H -> SparsePauliOp decomposition
  calibration.py           # Live IBM calibration pull + qubit classification
  ansatz.py                # Hardware-efficient ansatz for heavy-hex topology
  runtime_job.py           # Qiskit Runtime EstimatorV2/SamplerV2 submission
  conserved.py             # Five conserved quantities (E1, L2, L4, omega_bar, phi_bar)
  optimizer.py             # SPSA + L1 tent regularizer toward 2phi-equilibrium
  plotting.py              # Publication-quality matplotlib visualizations
  experiment.py            # Main entry point
```

## The Hamiltonian

```
H = Sum_i (p_i^2 / 2)                               [kinetic]
  + (omega_0^2 / 2) Sum_i (1 - cos theta_i)         [potential]
  + Sum_{i<j} (alpha_i * alpha_j / N) cos(theta_i - theta_j)  [coupling]
```

Mapped to qubits: `cos theta -> Z`, `sin theta -> X`, `p -> Y`, giving:

```
H_q = -(J/2) Sum_{<i,j>} (X_i X_j + Y_i Y_j)       [kinetic hopping]
    + (omega_0^2/2) Sum_i (I - Z_i)                   [on-site potential]
    + (1/N) Sum_{i<j} alpha_i alpha_j (Z_i Z_j + X_i X_j)  [anti-resonant coupling]
```

## Weight Modes

| Mode | Base | Character |
|------|------|-----------|
| `golden` | phi = 1.618... | Most balanced anti-resonance |
| `silver` | delta = 2.414... | Steep separation |
| `plastic` | rho = 1.325... | Gentlest separation |
| `bronze` | beta_3 = 3.303... | Very steep |
| `cocktail` | 0.4*phi + 0.3*e + 0.3*pi | 3D quasiperiodic torus |
| `chaotic_logistic` | r=4 logistic map | Fully ergodic, zero periodic points |
| `uniform` (baseline) | 1/N | Rational, resonance-prone |
| `harmonic` (baseline) | 1/k | Rational, resonance-prone |

## The "Unhinged" Quantum Feedback Loop

Every 10 SPSA iterations, a small 8-qubit auxiliary circuit simulates the quantum logistic map. Its measurement outcomes generate chaotic weight perturbations that are fed back into the classical optimizer, injecting true quantum randomness into the optimization trajectory.

## Citation

```bibtex
@software{knopp2026qgp,
  author = {Knopp, Christian},
  title = {Quantum Golden Pendulum Chaos Engine},
  year = {2026},
  url = {https://github.com/Zynerji/QuantumGoldenPendulum}
}
```

## License

MIT
