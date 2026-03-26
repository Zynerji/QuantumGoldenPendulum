"""Compute all 10 derived metrics from IBM Marrakesh experiment results."""

import json
import csv
import math

import numpy as np
from scipy import stats

with open("results/experiment_marrakesh_20q.json") as f:
    data = json.load(f)

modes = ["bronze", "cocktail", "golden", "chaotic_logistic", "uniform", "harmonic"]
PHI = (1 + math.sqrt(5)) / 2
results = {}
for mode in modes:
    results[mode] = {"energies": np.array(data[mode]["energies"])}

print("=" * 70)
print("DERIVED METRICS FROM IBM MARRAKESH EXPERIMENT")
print("=" * 70)

# 1. Late-Stage Momentum (LSM)
print("\n1. LATE-STAGE MOMENTUM (LSM)")
print("   Linear regression slope of energy over final 10 iterations")
for mode in modes:
    e = results[mode]["energies"]
    x = np.arange(len(e) - 10, len(e))
    slope, _, _, _, _ = stats.linregress(x, e[-10:])
    results[mode]["lsm"] = round(slope, 3)
    print(f"   {mode:<22s}: {slope:+.3f}")

# 2. Energy Volatility Decay Rate (lambda)
print("\n2. ENERGY VOLATILITY DECAY RATE (lambda)")
print("   Exponential fit to rolling 5-step std deviation")
for mode in modes:
    e = results[mode]["energies"]
    stds = [np.std(e[max(0, i - 4) : i + 1]) for i in range(4, len(e))]
    stds = np.maximum(np.array(stds), 1e-10)
    log_stds = np.log(stds)
    x = np.arange(len(log_stds))
    slope, _, _, _, _ = stats.linregress(x, log_stds)
    lam = -slope
    results[mode]["lambda"] = round(lam, 3)
    print(f"   {mode:<22s}: {lam:.3f}")

# 3. Convergence Half-Life (tau_half)
print("\n3. CONVERGENCE HALF-LIFE (tau_1/2)")
print("   Steps to reach 50% of best-energy improvement")
for mode in modes:
    e = results[mode]["energies"]
    e0 = e[0]
    e_best = min(e)
    half_target = e0 + 0.5 * (e_best - e0)
    tau = len(e)
    for i, val in enumerate(e):
        if val <= half_target:
            tau = i + 1
            break
    results[mode]["tau_half"] = round(tau, 1)
    print(f"   {mode:<22s}: {tau:.1f} steps")

# 4. Trajectory Autocorrelation Length (ACL)
print("\n4. TRAJECTORY AUTOCORRELATION LENGTH (ACL)")
print("   Lag where autocorrelation drops below 0.3")
for mode in modes:
    e = results[mode]["energies"]
    e_centered = e - np.mean(e)
    n = len(e)
    acl = n
    for lag in range(1, n):
        if lag >= n // 2:
            break
        corr = np.corrcoef(e_centered[: n - lag], e_centered[lag:])[0, 1]
        if np.isnan(corr) or corr < 0.3:
            acl = lag
            break
    results[mode]["acl"] = acl
    print(f"   {mode:<22s}: {acl} steps")

# 5. NAARG
print("\n5. NOISE-AMPLIFIED ANTI-RESONANCE GAIN (NAARG)")
print("   (Best energy - uniform best) / wall_time * 1000")
e_unif_best = data["uniform"]["best_energy"]
for mode in modes:
    if mode in ("uniform", "harmonic"):
        results[mode]["naarg"] = 0.0
        continue
    e_best = data[mode]["best_energy"]
    wall = data[mode]["wall_time_s"]
    naarg = (e_best - e_unif_best) / wall * 1000
    results[mode]["naarg"] = round(naarg, 2)
    print(f"   {mode:<22s}: {naarg:+.2f}")

# 6. Effective Irrationality Index (EII)
print("\n6. EFFECTIVE IRRATIONALITY INDEX (EII)")
print("   |E_best - E_harm| / dynamic_range * R^2")
bases = {
    "golden": PHI,
    "bronze": (3 + math.sqrt(13)) / 2,
    "cocktail": 0.4 * PHI + 0.3 * math.e + 0.3 * math.pi,
    "chaotic_logistic": 2.0,
}
e_harm = data["harmonic"]["best_energy"]
for mode in ["bronze", "cocktail", "golden", "chaotic_logistic"]:
    e_best = data[mode]["best_energy"]
    e = results[mode]["energies"]
    x = np.arange(len(e))
    _, _, r_value, _, _ = stats.linregress(x, e)
    r2 = r_value ** 2
    base = bases[mode]
    dr = base ** 19
    eii = abs(e_best - e_harm) / max(dr, 1) * r2
    results[mode]["eii"] = round(eii, 6)
    print(f"   {mode:<22s}: {eii:.6f} (R2={r2:.3f}, DR={dr:.1e})")

# 7. Cross-Mode Cosine Similarity
print("\n7. CROSS-MODE TRAJECTORY SIMILARITY (Cosine)")
for i, m1 in enumerate(modes):
    for m2 in modes[i + 1 :]:
        e1 = results[m1]["energies"]
        e2 = results[m2]["energies"]
        cos_sim = np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2))
        print(f"   {m1:<15s} <-> {m2:<15s}: {cos_sim:.2f}")

# 8. Quantum Entropy Injection Rate
print("\n8. QUANTUM ENTROPY INJECTION RATE")
non_feedback = ["golden", "bronze", "cocktail"]
avg_var = np.mean([np.var(np.diff(results[m]["energies"])) for m in non_feedback])
chaotic_var = np.var(np.diff(results["chaotic_logistic"]["energies"]))
injection_rate = (chaotic_var - avg_var) / avg_var if avg_var > 0 else 0
print(f"   Chaotic variance: {chaotic_var:.4f}")
print(f"   Non-feedback avg: {avg_var:.4f}")
print(f"   Injection rate:   {injection_rate:+.3f} ({injection_rate * 100:+.1f}%)")
results["chaotic_logistic"]["entropy_injection"] = round(injection_rate, 3)

# 9. Composite Score (Hardware-Optimized Anti-Resonance Hierarchy)
print("\n9. HARDWARE-OPTIMIZED ANTI-RESONANCE HIERARCHY")

# Compute NRAG*
e_unif = data["uniform"]["best_energy"]
denom = e_unif - e_harm
for mode in modes:
    e_best = data[mode]["best_energy"]
    e_30 = data[mode]["energies"][-1]
    energy_ratio = (e_best - e_harm) / denom
    stability = 1.0 if e_30 <= e_best * 0.999 else e_best / e_30
    results[mode]["nrag_star"] = energy_ratio * stability

# Normalize and combine
metric_keys = ["nrag_star", "lsm_neg", "lambda", "naarg"]
for mode in modes:
    results[mode]["lsm_neg"] = -results[mode]["lsm"]  # negate: more negative slope = better

raw_vals = {}
for mk in metric_keys:
    raw_vals[mk] = [results[m][mk] for m in modes]

normalized = {mode: {} for mode in modes}
for mk in metric_keys:
    vals = raw_vals[mk]
    vmin, vmax = min(vals), max(vals)
    rng = vmax - vmin if vmax != vmin else 1.0
    for mode in modes:
        normalized[mode][mk] = (results[mode][mk] - vmin) / rng

for mode in modes:
    score = sum(normalized[mode].values()) / len(metric_keys) * 10
    results[mode]["composite"] = round(score, 2)
    print(f"   {mode:<22s}: {score:.2f}")

# 10. 156-qubit Scaling Prediction
print("\n10. PREDICTED 156-QUBIT SCALING")
bronze_per_qubit = data["bronze"]["best_energy"] / 20
predicted_156 = bronze_per_qubit * 156
print(f"   Bronze per-qubit gain: {bronze_per_qubit:.3f}")
print(f"   Predicted 156-qubit:   {predicted_156:.1f}")

# Save JSON
derived = {}
for mode in modes:
    derived[mode] = {
        "best_energy": round(data[mode]["best_energy"], 6),
        "best_step": data[mode]["best_step"],
        "LSM": results[mode]["lsm"],
        "lambda_volatility_decay": results[mode]["lambda"],
        "tau_half": results[mode]["tau_half"],
        "ACL": results[mode]["acl"],
        "NRAG_star": round(results[mode]["nrag_star"], 4),
        "composite_score": results[mode]["composite"],
    }
    if mode not in ("uniform", "harmonic"):
        derived[mode]["NAARG"] = results[mode].get("naarg", 0)
        derived[mode]["EII"] = results[mode].get("eii", 0)
    if mode == "chaotic_logistic":
        derived[mode]["entropy_injection_rate"] = results[mode]["entropy_injection"]

derived["_metadata"] = {
    "predicted_156q_bronze": round(predicted_156, 1),
    "E_harmonic": round(e_harm, 6),
    "E_uniform": round(e_unif, 6),
}

with open("results/derived_metrics.json", "w") as f:
    json.dump(derived, f, indent=2)

# Save CSV
with open("results/derived_metrics.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow([
        "mode", "best_energy", "best_step", "LSM", "lambda",
        "tau_half", "ACL", "NRAG_star", "NAARG", "EII", "composite_score",
    ])
    for mode in modes:
        d = derived[mode]
        w.writerow([
            mode, d["best_energy"], d["best_step"], d["LSM"],
            d["lambda_volatility_decay"], d["tau_half"], d["ACL"],
            d["NRAG_star"], d.get("NAARG", ""), d.get("EII", ""),
            d["composite_score"],
        ])

print("\nSaved: results/derived_metrics.json, results/derived_metrics.csv")
