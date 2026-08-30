import asyncio
import json
from collections import Counter
from pathlib import Path

from ml.evaluation.families import run_family_diagnostics, sliced_distributions
from ml.training.artifacts import write_json
from ml.training.config import load_training_config
from ml.training.dataset import assemble_benchmark, schema_hashes
from ml.training.leakage import audit_model_matrix
from ml.training.splitting import manifest_hash, split_chronologically
from packages.synthetic.v2_validation import validate_hardened_v2


async def main() -> None:
    config_path = Path("configs/ml/model-v2.yaml")
    config = load_training_config(config_path).model_copy(
        update={"benchmark_seed": 24681, "transaction_count": 20_000}
    )
    dataset = await assemble_benchmark(config)
    split = split_chronologically(dataset.metadata, config.split_ratios)
    audit = audit_model_matrix(
        dataset.X[split.train], dataset.y[split.train], dataset.feature_names
    )
    family = run_family_diagnostics(dataset, split, config, include_leave_one_family_out=False)
    rings = {item.ring_id: item.scenario for item in dataset.metadata if item.ring_id is not None}
    requested_distributions = sliced_distributions(
        dataset,
        (
            "ip_txn_count_10m",
            "device_txn_count_10m",
            "device_failed_txn_count_10m",
            "customer_txn_count_1h",
            "account_age_hours",
            "historical_customers_on_current_device",
            "historical_instruments_on_current_device",
        ),
    )
    result = {
        "purpose": "synthetic-v2 development-seed validation; not final test evidence",
        "dataset": dataset.manifest.model_dump(mode="json"),
        "ring_count": len(rings),
        "rings_by_scenario": dict(sorted(Counter(rings.values()).items())),
        "hardening_validation": validate_hardened_v2(dataset.synthetic_dataset),
        "split": split.manifest,
        "split_manifest_hash": manifest_hash(split.manifest),
        "leakage_audit": audit.as_dict(),
        "family_diagnostics": family,
        "selected_distributions": requested_distributions,
        "runtimes": dataset.runtimes,
        "schema_hashes": schema_hashes(Path.cwd()),
    }
    output = Path("ml/artifacts/model-v2/development_diagnostics.json")
    write_json(output, result)
    print(
        json.dumps(
            {
                "output": str(output),
                "dataset": result["dataset"],
                "rings_by_scenario": result["rings_by_scenario"],
                "hardening_validation": result["hardening_validation"],
                "runtimes": result["runtimes"],
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
