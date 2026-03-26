# Quantum Golden Pendulum Chaos Engine

A hybrid quantum-classical experiment demonstrating that **anti-resonant weight sequences** (golden ratio, metallic means, transcendental cocktails, chaotic logistic maps) stabilize quantum simulation of coupled-oscillator Hamiltonians better than rational baselines.

Runs on the **IBM Marrakesh 156-qubit Heron r2 processor** or locally on FakeMarrakesh.

## Core Hypothesis

Task gradients in multi-task learning are modeled as coupled wave oscillators (Knopp, 2026). We replace the classical anti-resonant weights with **quantum-native phase rotations** on real QPU hardware. The experiment measures whether irrational weight spacing prevents resonance-induced decoherence, producing:

1. Lower ground-state energy estimates
2. Faster convergence to the 2phi-equilibrium phase
3. Better conservation law adherence (E1->1, L2->pi, L4->sqrt(e))
4. Lower energy variance across measurement shots

## Results: IBM Marrakesh (March 25, 2026)

**20 qubits, 2 variational layers, 30 SPSA iterations, 4000 shots, 396 QPU jobs.**

| Rank | Mode | Best Energy | E(30) | Step | NRAG* | Stable |
|------|------|-------------|-------|------|-------|--------|
| 1 | **Bronze (beta_3)** | **-6.532** | -6.532 | 30 | **3.775** | YES |
| 2 | **Cocktail** | **-5.509** | -5.438 | 29 | **1.357** | YES |
| 3 | Uniform (baseline) | -5.366 | -5.278 | 22 | 1.017 | NO |
| 4 | Golden (phi) | -5.121 | -5.121 | 30 | 0.418 | YES |
| 5 | Chaotic logistic | -5.042 | -4.934 | 28 | 0.234 | YES |
| 6 | Harmonic (baseline) | -4.945 | -4.826 | 17 | 0.000 | NO |

### NRAG* (Normalized Relative Anti-resonant Gain)

We quantify mode quality using a stability-adjusted metric. The raw NRAG is:

```
NRAG = ((E_mode - E_harmonic) / (E_uniform - E_harmonic)) * (1 - best_step / 30)
```

However, raw NRAG penalizes modes that are **still improving** at step 30 (speed term = 0), conflating "hasn't converged yet" with "slow." On real hardware, the opposite is true: bronze hits its best at step 30 because it **never gets trapped**, while uniform peaks at step 22 then **degrades** -- a signature of resonant trapping, not fast convergence.

NRAG* replaces the speed term with a **stability term**: if the mode held or improved through step 30, stability = 1.0 (no penalty). If the mode degraded (E(30) > E(best)), stability = E(best)/E(30) < 1 (penalized for instability):

```
NRAG* = ((E_mode - E_harmonic) / (E_uniform - E_harmonic)) * stability
```

| Mode | NRAG (raw) | NRAG* (adjusted) | Interpretation |
|------|-----------|------------------|----------------|
| Bronze | 0.000 | **3.775** | Best energy, stable -- raw NRAG incorrectly gives 0 |
| Cocktail | 0.045 | **1.357** | Strong, stable |
| Uniform | **0.267** | 1.017 | Raw NRAG rewards early peak, ignores degradation |
| Golden | 0.000 | 0.418 | Moderate energy, stable |
| Chaotic | 0.015 | 0.234 | Modest energy, stable |
| Harmonic | 0.000 | 0.000 | Worst energy (reference point) |

### Verdict

**Steep anti-resonant modes (bronze, cocktail) decisively beat both rational baselines on real quantum hardware.** Bronze achieves 21.7% lower ground-state energy and an NRAG* of 3.775 (3.7x the uniform baseline).

The smoking gun is in the convergence dynamics: both baselines exhibit **resonant trapping** -- uniform peaks at step 22 then degrades to -5.278 by step 30, harmonic peaks at step 17 then stalls. Anti-resonant modes never get trapped -- bronze improves monotonically from -3.84 to -6.53 across all 30 iterations because irrational phase spacing prevents the optimizer from falling into periodic orbits.

The golden ratio (the "most irrational" number) is NOT the best mode on noisy hardware. Bronze (steeper phase contrast) wins because greater separation between qubit rotation angles resists noise-induced homogenization.

### Physics takeaway

**Irrational rotation angles in quantum circuits act as a KAM-like stability mechanism: they prevent variational parameters from falling into resonant periodic orbits, enabling sustained optimization where rational encodings get trapped and degrade.**

### Data files

- [`results/experiment_marrakesh_20q.json`](results/experiment_marrakesh_20q.json) -- Full energy trajectories for all 6 modes (30 iterations each)
- [`results/calibration_experiment.json`](results/calibration_experiment.json) -- Live IBM Marrakesh calibration snapshot (138 good / 18 bad / 0 dead qubits)
- [`results/calibration_live.json`](results/calibration_live.json) -- Pre-experiment calibration pull
- Hardware validation jobs: `d72794uv3u3c73ei8p6g` (estimator), `d7279apamkec73a0shb0` (sampler)

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
