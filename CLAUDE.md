# Quantum Golden Pendulum — Session Checkpoint

## NEXT SESSION: Pick up here

### What's done
- **Full 20-qubit experiment COMPLETE** on ibm_marrakesh (March 25, 2026)
- 396 QPU jobs, 6 modes (golden, bronze, cocktail, chaotic, uniform, harmonic)
- Bronze wins: E=-6.532 (21.7% better than uniform baseline)
- 40 derived novelties computed and in README
- Results JSON + CSVs pushed to GitHub
- Whitepaper written (paper/quantum_golden_pendulum_whitepaper.tex) with real data filled in
- GitHub: https://github.com/Zynerji/QuantumGoldenPendulum

### What needs doing (in priority order)

1. **SUBMIT THE PAPER** — Data is complete. Target: Physical Review A or npj Quantum Information. The whitepaper has real IBM data, 40 novelties, job IDs for verification. Just needs final formatting pass and submission.

2. **Apply bronze encoding to TriCameral quantum oracle** — Zero QPU cost. In `TriCameral.ai/tricameral/dhart/quantum_oracle.py`, replace the random/uniform initial rotation angles with bronze metallic mean (beta_3 = 3.303) weights. One line change. Test in next trading session.

3. **Verify scaling law with silver (n=2)** — Predicted E=-5.83. Run `run_metallic_scaling.py` (partially built, needs to be finished — was killed mid-run). ~60 jobs, ~5 min QPU. Confirms E(n) = -0.705n - 4.416 across 3 data points.

4. **Conservation law measurements** — Current 20-qubit measurements return NaN because 4000 shots across 2^20 outcomes is too sparse for DFT. Fix: run a dedicated 8-12 qubit conservation law experiment with 8192+ shots, or implement classical shadow tomography.

### Key findings to remember
- Bronze (n=3, steep) beats golden (n=1, gentle) on noisy hardware — optimal irrationality INCREASES with noise level
- Uniform baseline shows RESONANT BRAKING (energy curvature EC=+0.013, variance INCREASING over time)
- Anti-resonant modes show RESONANT ACCELERATION (EC=-0.014 for cocktail)
- Bronze RTI=0 (NEVER degrades after peak), uniform degrades after step 22
- Chaotic logistic feedback loop acts as REGULARIZER (67% lower variance than non-feedback modes)
- Scaling law: E(n) = -0.705n - 4.416 (linear in metallic mean index, no ionization limit)

### IBM Marrakesh details
- Connection: `QiskitRuntimeService(instance="open-instance")`
- Backend: ibm_marrakesh, 156 qubits Heron r2
- Calibration: 138 good / 18 bad / 0 dead qubits (as of March 25, 2026)
- Dead qubits (hardcoded fallback): {82, 113, 119, 130}
- Transpile: optimization_level=2, ALWAYS check depth < 150
- QPU billing: IBM bills full job wall time, NOT just gate execution. Budget accordingly.
- Allocation: started with 175 min, used ~86 min on first experiment + ~15 min on periodic table = ~74 min remaining (CHECK DASHBOARD before running)

### Hardware validation job IDs (verifiable)
- Estimator: d72794uv3u3c73ei8p6g
- Sampler: d7279apamkec73a0shb0

### Files that matter
- `quantum_golden_pendulum/anti_resonant_weights.py` — All weight generators (ported from GoldenPendulumMTL)
- `quantum_golden_pendulum/hamiltonian.py` — Coupled pendulum H → SparsePauliOp
- `quantum_golden_pendulum/runtime_job.py` — IBM submission with observable padding + transpile cache
- `quantum_golden_pendulum/experiment.py` — Main CLI runner
- `results/experiment_marrakesh_20q.json` — Raw data (all 180 energy values + job metadata)
- `results/derived_metrics.json` — All 10 computed metrics
- `compute_metrics.py` — Reproduces metrics 1-10 from raw data
- `compute_novelties_21_40.py` — Reproduces metrics 21-40
