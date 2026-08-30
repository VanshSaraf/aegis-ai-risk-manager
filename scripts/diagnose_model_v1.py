import asyncio
import json
from pathlib import Path

from ml.evaluation.families import run_family_diagnostics
from ml.training.artifacts import write_json
from ml.training.config import load_training_config
from ml.training.dataset import assemble_benchmark
from ml.training.splitting import split_chronologically


async def main() -> None:
    config_path = Path("configs/ml/model-v1.yaml")
    config = load_training_config(config_path)
    dataset = await assemble_benchmark(config)
    split = split_chronologically(dataset.metadata, config.split_ratios)
    result = run_family_diagnostics(dataset, split, config, include_leave_one_family_out=True)
    result["dataset_version"] = dataset.manifest.dataset_version
    result["runtimes"] = dataset.runtimes
    output = Path("ml/artifacts/model-v1/diagnostics.json")
    write_json(output, result)
    print(json.dumps({"output": str(output), "runtimes": dataset.runtimes}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
