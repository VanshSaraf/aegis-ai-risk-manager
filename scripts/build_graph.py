import argparse
import asyncio
import json

from apps.api.app.db.session import SessionFactory
from packages.graph_engine.registry import GRAPH_VERSION
from packages.graph_engine.service import backfill_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build point-in-time graph assessments and structural clusters"
    )
    parser.add_argument("--graph-version", default=GRAPH_VERSION, choices=[GRAPH_VERSION])
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    async with SessionFactory() as session:
        result = await backfill_graph(session, limit=args.limit)
    print(
        json.dumps(
            {
                "graph_version": args.graph_version,
                "assessments": len(result.assessments),
                "nodes": len(result.state.node_first_seen),
                "edges": len(result.state.edges),
                "detected_structural_clusters": len(result.clusters),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
