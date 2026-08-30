import argparse
import asyncio
import json

from apps.api.app.db.session import SessionFactory
from packages.risk_engine.features.registry import FEATURE_VERSION
from packages.risk_engine.features.service import backfill_features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build immutable point-in-time feature snapshots")
    parser.add_argument("--feature-version", default=FEATURE_VERSION, choices=[FEATURE_VERSION])
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    async with SessionFactory() as session:
        vectors = await backfill_features(session, limit=args.limit)
    print(
        json.dumps(
            {
                "feature_version": args.feature_version,
                "feature_count": len(vectors[0].values) if vectors else 0,
                "snapshots": len(vectors),
                "with_history": sum(vector.max_source_event_time is not None for vector in vectors),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
