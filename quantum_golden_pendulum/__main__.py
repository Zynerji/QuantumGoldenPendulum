"""Allow running as `python -m quantum_golden_pendulum`."""
from .experiment import main

if __name__ == "__main__":
    raise SystemExit(main())
