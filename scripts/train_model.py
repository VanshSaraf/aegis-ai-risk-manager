import argparse
import json
from pathlib import Path

from ml.evaluation.benchmark import run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and optionally test Phase 5 models.")
    parser.add_argument("--config", type=Path, default=Path("configs/ml/model-v1.yaml"))
    parser.add_argument("--artifact-directory", type=Path, default=Path("ml/artifacts/model-v1"))
    parser.add_argument(
        "--evaluate-test",
        action="store_true",
        help="Explicitly unseal and evaluate the held-out test partition.",
    )
    parser.add_argument("--transactions", type=int, help="Smoke-only transaction-count override.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run(
        args.config,
        args.artifact_directory,
        evaluate_test=args.evaluate_test,
        transaction_count_override=args.transactions,
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
