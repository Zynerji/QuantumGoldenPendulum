"""Compute novelties 21-40 from IBM Marrakesh experiment results."""

import json
import math

import numpy as np
from scipy import stats

with open("results/experiment_marrakesh_20q.json") as f:
    data = json.load(f)

modes = ["bronze", "cocktail", "golden", "chaotic_logistic", "uniform", "harmonic"]
PHI = (1 + math.sqrt(5)) / 2

energies = {m: np.array(data[m]["energies"]) for m in modes}
diffs = {m: np.diff(energies[m]) for m in modes}

print("=" * 70)
print("NOVELTIES 21-40: DEEP STRUCTURE ANALYSIS")
print("=" * 70)

# 21
print("\n21. RECOVERY SPEED AFTER SETBACK (RSS)")
print("    Avg steps to recover after an energy increase.")
for mode in modes:
    d = diffs[mode]
    setbacks = np.where(d > 0)[0]
    if len(setbacks) == 0:
        print(f"    {mode:<22s}: no setbacks")
        continue
    recovery_times = []
    for sb in setbacks:
        e_before = energies[mode][sb]
        recovered = False
        for j in range(sb + 1, len(energies[mode])):
            if energies[mode][j] <= e_before:
                recovery_times.append(j - sb)
                recovered = True
                break
        if not recovered:
            recovery_times.append(len(energies[mode]) - sb)
    print(f"    {mode:<22s}: {np.mean(recovery_times):.1f} steps ({len(setbacks)} setbacks)")

# 22
print("\n22. DOWNHILL/UPHILL ASYMMETRY RATIO (DUAR)")
print("    |mean downhill step| / |mean uphill step|. >1 = falls harder than rises.")
for mode in modes:
    d = diffs[mode]
    down = d[d < 0]
    up = d[d > 0]
    if len(up) == 0 or len(down) == 0:
        print(f"    {mode:<22s}: N/A")
        continue
    ratio = abs(np.mean(down)) / abs(np.mean(up))
    print(f"    {mode:<22s}: {ratio:.3f}")

# 23
print("\n23. SPECTRAL ENTROPY OF ENERGY TRAJECTORY")
print("    Shannon entropy of FFT power spectrum. Higher = more chaotic path.")
for mode in modes:
    e = energies[mode] - np.mean(energies[mode])
    fft = np.abs(np.fft.rfft(e))[1:]
    psd = fft ** 2
    psd = psd / psd.sum()
    psd = psd[psd > 0]
    se = -np.sum(psd * np.log2(psd))
    print(f"    {mode:<22s}: {se:.3f} bits")

# 24
print("\n24. ESCAPE VELOCITY (EV)")
print("    Largest single-step energy drop.")
for mode in modes:
    d = diffs[mode]
    ev = abs(min(d))
    step = np.argmin(d) + 1
    print(f"    {mode:<22s}: {ev:.4f} at step {step}")

# 25
print("\n25. STAGNATION RATIO (SR)")
print("    Fraction of steps where |delta_E| < 0.05.")
for mode in modes:
    d = diffs[mode]
    stag = np.sum(np.abs(d) < 0.05) / len(d)
    print(f"    {mode:<22s}: {stag:.3f}")

# 26
print("\n26. FIRST PASSAGE TIME TO E < -5.0")
for mode in modes:
    e = energies[mode]
    fpt = None
    for i, val in enumerate(e):
        if val < -5.0:
            fpt = i + 1
            break
    print(f"    {mode:<22s}: {'step ' + str(fpt) if fpt else 'never'}")

# 27
print("\n27. TERMINAL MOMENTUM (mean of last 5 energy deltas)")
for mode in modes:
    d = diffs[mode]
    tm = np.mean(d[-5:])
    print(f"    {mode:<22s}: {tm:+.4f}")

# 28
print("\n28. IMPROVEMENT CONCENTRATION INDEX (ICI)")
print("    Fraction of total improvement from the best 5 steps.")
for mode in modes:
    d = diffs[mode]
    downs = d[d < 0]
    total_improvement = abs(downs.sum())
    if total_improvement < 1e-10:
        continue
    top5 = np.sort(downs)[:5]
    top5_improvement = abs(top5.sum())
    ici = top5_improvement / total_improvement
    print(f"    {mode:<22s}: {ici:.3f} ({ici*100:.1f}% from top 5 steps)")

# 29
print("\n29. HURST EXPONENT (long-range dependence)")
print("    H > 0.5 = trending. H < 0.5 = mean-reverting.")
for mode in modes:
    e = energies[mode]
    n = len(e)
    cumdev = np.cumsum(e - np.mean(e))
    R = max(cumdev) - min(cumdev)
    S = np.std(e)
    H = np.log(R / S) / np.log(n) if S > 0 and R > 0 else 0.5
    print(f"    {mode:<22s}: H = {H:.3f}")

# 30
print("\n30. ANTI-RESONANT SHARPE RATIO (ARSR)")
print("    mean(delta_E) / std(delta_E). More negative = more consistent descent.")
for mode in modes:
    d = diffs[mode]
    sharpe = np.mean(d) / np.std(d) if np.std(d) > 1e-10 else 0
    print(f"    {mode:<22s}: {sharpe:.3f}")

# 31
print("\n31. TRAJECTORY JERKINESS (mean |d2E/dt2|)")
print("    Lower = smoother path through parameter space.")
for mode in modes:
    d2 = np.diff(energies[mode], n=2)
    jerk = np.mean(np.abs(d2))
    print(f"    {mode:<22s}: {jerk:.4f}")

# 32
print("\n32. WALD-WOLFOWITZ RUNS TEST (non-randomness Z-score)")
print("    |Z| > 1.96 = trajectory is NOT random walk.")
for mode in modes:
    d = diffs[mode]
    binary = (d < 0).astype(int)
    n1 = int(np.sum(binary))
    n2 = len(binary) - n1
    runs = 1 + int(np.sum(np.abs(np.diff(binary))))
    if n1 > 0 and n2 > 0:
        n = n1 + n2
        mu = 2 * n1 * n2 / n + 1
        var = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n ** 2 * (n - 1))
        z = (runs - mu) / np.sqrt(var) if var > 0 else 0
    else:
        z = 0
    print(f"    {mode:<22s}: Z = {z:+.3f} ({'STRUCTURED' if abs(z) > 1.96 else 'random-like'})")

# 33
print("\n33. OPTIMAL AVERAGING WINDOW")
print("    Window that best predicts final energy from rolling mean.")
for mode in modes:
    e = energies[mode]
    best_w, best_mse = 1, float("inf")
    for w in range(1, 15):
        rolling = np.convolve(e, np.ones(w) / w, mode="valid")
        mse = (rolling[-1] - e[-1]) ** 2
        if mse < best_mse:
            best_mse = mse
            best_w = w
    print(f"    {mode:<22s}: window = {best_w}")

# 34
print("\n34. ENERGY GAP AT MIDPOINT (step 15)")
best_base_15 = min(energies["uniform"][14], energies["harmonic"][14])
for mode in modes:
    gap = energies[mode][14] - best_base_15
    print(f"    {mode:<22s}: {gap:+.4f} vs best baseline ({best_base_15:.3f})")

# 35
print("\n35. TAIL RISK (largest energy increase in one step)")
for mode in modes:
    d = diffs[mode]
    worst = max(d)
    step = np.argmax(d) + 1
    print(f"    {mode:<22s}: +{worst:.4f} at step {step}")

# 36
print("\n36. CUMULATIVE ADVANTAGE vs UNIFORM (integral)")
for mode in modes:
    if mode == "uniform":
        continue
    adv = np.sum(energies[mode] - energies["uniform"])
    print(f"    {mode:<22s}: {adv:+.3f}")

# 37
print("\n37. ENERGY KURTOSIS")
print("    >0 = heavy tails (extreme events), <0 = light tails (consistent).")
for mode in modes:
    k = float(stats.kurtosis(energies[mode]))
    print(f"    {mode:<22s}: {k:+.3f}")

# 38
print("\n38. GAIN/PAIN RATIO (Sortino-like)")
print("    Total gains / total losses. Higher = more reward per unit of setback.")
for mode in modes:
    d = diffs[mode]
    gains = abs(d[d < 0].sum())
    pains = abs(d[d > 0].sum()) if np.any(d > 0) else 1e-10
    ratio = gains / pains
    print(f"    {mode:<22s}: {ratio:.3f}")

# 39
print("\n39. INFORMATION RATIO vs UNIFORM")
print("    (mean excess) / (tracking error). Active management score.")
for mode in modes:
    if mode == "uniform":
        continue
    excess = energies[mode] - energies["uniform"]
    ir = np.mean(excess) / np.std(excess) if np.std(excess) > 0 else 0
    print(f"    {mode:<22s}: {ir:+.3f}")

# 40
print("\n40. PREDICTED OPTIMAL ITERATION COUNT")
print("    Quadratic extrapolation: when does improvement stop?")
for mode in modes:
    e = energies[mode]
    x = np.arange(15, 30)
    y = e[15:]
    coeffs = np.polyfit(x, y, 2)
    a, b, c = coeffs
    if abs(a) > 1e-10:
        t_opt = -b / (2 * a)
        e_pred = np.polyval(coeffs, t_opt)
        if t_opt > 30:
            print(f"    {mode:<22s}: step {t_opt:.0f} (predicted E = {e_pred:.3f})")
        else:
            print(f"    {mode:<22s}: past optimum at step {t_opt:.0f}")
    else:
        print(f"    {mode:<22s}: linear trajectory (keep going)")
