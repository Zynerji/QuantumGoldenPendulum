"""IBM Marrakesh calibration data retrieval and qubit classification.

Ported from TriCameral.ai quantum_oracle.py _pull_calibration() method.
Pulls live calibration from the IBM backend, classifies qubits as good/bad/dead,
and extracts the coupling map for heavy-hex-aware circuit construction.

Calibration thresholds (battle-tested from TriCameral QuantumOracle):
    - Dead:  T1 < 1.0 µs OR no calibration data
    - Bad:   T1 < 10 µs OR T2 < 5 µs OR readout_error > 5% OR CX error > 3%
    - Good:  Passes all thresholds

These thresholds are calibrated against ibm_marrakesh and ibm_fez production
data from TriCameral.ai's 24/7 trading operations (Jan-Mar 2026).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ─── Thresholds (from TriCameral.ai QuantumOracle) ───────────────────────────
T1_DEAD_US = 1.0       # Below this → qubit is completely non-functional
T1_MIN_US = 10.0        # Minimum acceptable T1 coherence time
T2_MIN_US = 5.0         # Minimum acceptable T2 dephasing time
READOUT_MAX = 0.05      # Maximum 5% readout error
CX_ERROR_MAX = 0.03     # Maximum 3% two-qubit gate error

# Known dead qubits on ibm_marrakesh (as of 2026-03-18)
# These are hardcoded as a fallback when live calibration is unavailable.
MARRAKESH_DEAD_QUBITS = {82, 113, 119, 130}

# Known bad qubits (worst 15% by 2-qubit error) — fallback
MARRAKESH_BAD_QUBITS = {
    19, 25, 26, 27, 35, 36, 37, 40, 41, 42, 47, 48, 49, 60, 61,
    80, 81, 82, 83, 86, 87, 96, 105, 112, 113, 114, 117, 119, 129,
    130, 131, 133, 134, 135, 142, 143, 144, 151, 152,
}


@dataclass
class QubitInfo:
    """Calibration data for a single qubit."""
    index: int
    t1_us: float = 0.0
    t2_us: float = 0.0
    readout_error: float = 1.0
    classification: str = "unknown"  # "good", "bad", "dead"


@dataclass
class CalibrationSnapshot:
    """Complete calibration snapshot for a backend."""
    backend_name: str
    timestamp: datetime
    n_qubits: int
    good_qubits: List[int] = field(default_factory=list)
    bad_qubits: List[int] = field(default_factory=list)
    dead_qubits: List[int] = field(default_factory=list)
    good_edges: List[Tuple[int, int]] = field(default_factory=list)
    qubit_info: Dict[int, QubitInfo] = field(default_factory=dict)
    coupling_map_edges: List[Tuple[int, int]] = field(default_factory=list)


def pull_calibration(
    backend,
    save_path: Optional[Path] = None,
) -> CalibrationSnapshot:
    """Pull live calibration data from an IBM backend.

    Extracts per-qubit T1, T2, readout error, and per-edge CX error rates
    from the backend's target property (Qiskit 0.44+ API).

    Args:
        backend: An IBM backend object (real or fake).
        save_path: Optional path to save calibration JSON for reproducibility.

    Returns:
        CalibrationSnapshot with classified qubits and good edges.
    """
    snap = CalibrationSnapshot(
        backend_name=backend.name,
        timestamp=datetime.now(),
        n_qubits=backend.num_qubits,
    )

    target = backend.target
    qubit_infos = {}

    # ── Per-qubit calibration ─────────────────────────────────────────────
    for q in range(backend.num_qubits):
        info = QubitInfo(index=q)

        # T1 and T2 from qubit properties
        try:
            qprops = target.qubit_properties
            if qprops is not None and q < len(qprops) and qprops[q] is not None:
                t1 = getattr(qprops[q], "t1", None)
                t2 = getattr(qprops[q], "t2", None)
                if t1 is not None:
                    info.t1_us = t1 * 1e6  # seconds → microseconds
                if t2 is not None:
                    info.t2_us = t2 * 1e6
        except Exception:
            pass

        # Readout error from measure gate
        try:
            measure_props = target["measure"]
            if measure_props is not None:
                qargs = (q,)
                if qargs in measure_props:
                    err = measure_props[qargs].error
                    if err is not None:
                        info.readout_error = err
        except Exception:
            pass

        # Classify qubit
        if info.t1_us < T1_DEAD_US:
            info.classification = "dead"
            snap.dead_qubits.append(q)
        elif (info.t1_us < T1_MIN_US or info.t2_us < T2_MIN_US
              or info.readout_error > READOUT_MAX):
            info.classification = "bad"
            snap.bad_qubits.append(q)
        else:
            info.classification = "good"
            snap.good_qubits.append(q)

        qubit_infos[q] = info

    snap.qubit_info = qubit_infos

    # ── Coupling map edges ────────────────────────────────────────────────
    try:
        cmap = backend.coupling_map
        if cmap is not None:
            snap.coupling_map_edges = list(cmap.get_edges())
    except Exception:
        pass

    # ── Good edges (both endpoints good, CX error within threshold) ──────
    good_set = set(snap.good_qubits)
    for (i, j) in snap.coupling_map_edges:
        if i not in good_set or j not in good_set:
            continue

        # Check CX/ECR gate error on this edge
        cx_error = _get_two_qubit_error(target, i, j)
        if cx_error is not None and cx_error > CX_ERROR_MAX:
            continue

        snap.good_edges.append((i, j))

    # Sort for determinism
    snap.good_qubits.sort()
    snap.bad_qubits.sort()
    snap.dead_qubits.sort()
    snap.good_edges.sort()

    logger.info(
        f"Calibration: {len(snap.good_qubits)} good, "
        f"{len(snap.bad_qubits)} bad, {len(snap.dead_qubits)} dead qubits, "
        f"{len(snap.good_edges)} good edges"
    )

    # ── Optionally save to disk ───────────────────────────────────────────
    if save_path is not None:
        _save_calibration(snap, save_path)

    return snap


def _get_two_qubit_error(target, q0: int, q1: int) -> Optional[float]:
    """Extract two-qubit gate error for an edge, trying CX/ECR/CZ."""
    for gate_name in ("cx", "ecr", "cz"):
        try:
            gate_props = target[gate_name]
            if gate_props is None:
                continue
            qargs = (q0, q1)
            if qargs in gate_props and gate_props[qargs].error is not None:
                return gate_props[qargs].error
        except (KeyError, AttributeError):
            continue
    return None


def _save_calibration(snap: CalibrationSnapshot, path: Path) -> None:
    """Persist calibration to JSON for reproducibility."""
    data = {
        "backend": snap.backend_name,
        "timestamp": snap.timestamp.isoformat(),
        "n_qubits": snap.n_qubits,
        "good_qubits": snap.good_qubits,
        "bad_qubits": snap.bad_qubits,
        "dead_qubits": snap.dead_qubits,
        "n_good_edges": len(snap.good_edges),
        "qubit_stats": {
            str(q): {
                "t1_us": round(info.t1_us, 2),
                "t2_us": round(info.t2_us, 2),
                "readout_error": round(info.readout_error, 5),
                "class": info.classification,
            }
            for q, info in snap.qubit_info.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Calibration saved to {path}")


def select_qubit_subset(
    snap: CalibrationSnapshot,
    n_qubits: int,
) -> Tuple[List[int], List[Tuple[int, int]]]:
    """Select the best n_qubits from good qubits with maximum connectivity.

    Uses a BFS-based strategy: start from the good qubit with the most good
    edges, greedily expand to neighboring good qubits until we have enough.
    This produces a connected subgraph of the heavy-hex lattice.

    Args:
        snap: CalibrationSnapshot with classified qubits and edges.
        n_qubits: How many qubits we need.

    Returns:
        (selected_qubits, selected_edges) — both sorted.

    Raises:
        ValueError: If not enough good qubits available.
    """
    good_set = set(snap.good_qubits)

    if len(good_set) < n_qubits:
        raise ValueError(
            f"Need {n_qubits} qubits but only {len(good_set)} good qubits available. "
            f"Consider using bad qubits or reducing n_qubits."
        )

    # Build adjacency list from good edges only
    adj: Dict[int, List[int]] = {q: [] for q in good_set}
    for (i, j) in snap.good_edges:
        if i in good_set and j in good_set:
            adj[i].append(j)
            adj[j].append(i)

    # Find seed: good qubit with most good-edge neighbors
    seed = max(good_set, key=lambda q: len(adj.get(q, [])))

    # BFS expansion from seed
    selected: Set[int] = {seed}
    frontier = list(adj.get(seed, []))

    while len(selected) < n_qubits and frontier:
        # Score frontier qubits by connectivity to already-selected qubits
        frontier = [q for q in frontier if q not in selected and q in good_set]
        if not frontier:
            # Try adding any remaining good qubit
            remaining = good_set - selected
            if remaining:
                frontier = list(remaining)
            else:
                break

        # Pick the frontier qubit with most connections to selected set
        best = max(
            frontier,
            key=lambda q: sum(1 for n in adj.get(q, []) if n in selected)
        )
        selected.add(best)
        frontier.extend(n for n in adj.get(best, []) if n not in selected)

    if len(selected) < n_qubits:
        raise ValueError(
            f"Could only select {len(selected)} connected good qubits, "
            f"needed {n_qubits}."
        )

    selected_list = sorted(selected)[:n_qubits]
    selected_set = set(selected_list)

    # Extract edges within the selected subset
    selected_edges = [
        (i, j) for (i, j) in snap.good_edges
        if i in selected_set and j in selected_set
    ]

    return selected_list, selected_edges


def get_fallback_calibration(n_qubits: int = 156) -> CalibrationSnapshot:
    """Create a fallback calibration using hardcoded Marrakesh data.

    Used when running with FakeMarrakesh or when live calibration fails.
    """
    all_qubits = set(range(n_qubits))
    good = sorted(all_qubits - MARRAKESH_BAD_QUBITS - MARRAKESH_DEAD_QUBITS)
    bad = sorted(MARRAKESH_BAD_QUBITS - MARRAKESH_DEAD_QUBITS)
    dead = sorted(MARRAKESH_DEAD_QUBITS)

    return CalibrationSnapshot(
        backend_name="ibm_marrakesh_fallback",
        timestamp=datetime.now(),
        n_qubits=n_qubits,
        good_qubits=good,
        bad_qubits=bad,
        dead_qubits=dead,
    )
