#!/usr/bin/env python3
import argparse
import asyncio
from pathlib import Path

from apps.api.app.core.enums import ScenarioType
from apps.api.app.db.session import SessionFactory, engine
from packages.synthetic.config import load_generation_config
from packages.synthetic.service import format_generation_report, generate_and_ingest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and ingest a deterministic defensive Aegis dataset."
    )
    parser.add_argument("--config", type=Path, help="Scenario configuration YAML")
    parser.add_argument("--seed", type=int, help="Override the configured seed")
    parser.add_argument("--transactions", type=int, help="Override transaction count")
    parser.add_argument("--scenario", type=ScenarioType, choices=list(ScenarioType))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("ml/datasets/generated"),
        help="Root directory for manifest.json and events.jsonl",
    )
    parser.add_argument("--no-export", action="store_true")
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    config = load_generation_config(args.config)
    dataset_updates = {}
    if args.seed is not None:
        dataset_updates["seed"] = args.seed
    if args.transactions is not None:
        dataset_updates["transaction_count"] = args.transactions
    if dataset_updates:
        config = config.model_copy(
            update={"dataset": config.dataset.model_copy(update=dataset_updates)}
        )

    async with SessionFactory() as session:
        result = await generate_and_ingest(
            session,
            config,
            scenario=args.scenario,
            output_root=None if args.no_export else args.output_root,
        )
    await engine.dispose()
    print(format_generation_report(result))


if __name__ == "__main__":
    asyncio.run(run())
