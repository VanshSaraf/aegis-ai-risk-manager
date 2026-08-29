import pytest
from sqlalchemy import func, select

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType
from apps.api.app.db.session import SessionFactory
from apps.api.app.models import (
    AuditEvent,
    Customer,
    DatasetVersion,
    EntityEdge,
    RawEvent,
    ScenarioRun,
    Transaction,
)
from packages.synthetic import generate_dataset, load_generation_config
from packages.synthetic.service import generate_and_ingest

pytestmark = pytest.mark.integration


async def test_small_world_ingests_through_phase_one_pipeline(clean_database) -> None:
    config = load_generation_config()
    config = config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"transaction_count": 250})}
    )
    async with SessionFactory() as session:
        result = await generate_and_ingest(session, config)

        assert result.validation.status == "PASS"
        assert await session.scalar(select(func.count()).select_from(RawEvent)) == 250
        assert await session.scalar(select(func.count()).select_from(Transaction)) == 250
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 250
        assert await session.scalar(select(func.count()).select_from(DatasetVersion)) == 1
        assert await session.scalar(select(func.count()).select_from(ScenarioRun)) == 5
        assert await session.scalar(select(func.count()).select_from(Customer)) < 250
        assert await session.scalar(select(func.count()).select_from(EntityEdge)) < 1250

        transactions = (await session.scalars(select(Transaction))).all()
        assert all(transaction.scenario_run_id is not None for transaction in transactions)
        assert {transaction.ground_truth_label for transaction in transactions} == {
            GroundTruthLabel.LEGITIMATE,
            GroundTruthLabel.COORDINATED_ABUSE,
        }
        raw = (await session.scalars(select(RawEvent))).first()
        assert raw is not None
        assert not {
            "ground_truth_label",
            "ground_truth_scenario",
            "ground_truth_ring_id",
            "persona",
        }.intersection(raw.payload)

        runs = (await session.scalars(select(ScenarioRun))).all()
        assert {run.status for run in runs} == {"COMPLETED"}
        assert all(run.completed_at is not None for run in runs)


async def test_same_scenario_and_seed_can_be_ingested_twice(clean_database) -> None:
    config = load_generation_config()
    config = config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"seed": 991, "transaction_count": 80})}
    )
    scenario = ScenarioType.CARD_TESTING
    expected = generate_dataset(config, scenario)

    async with SessionFactory() as session:
        first = await generate_and_ingest(session, config, scenario=scenario)
        first_run_id = first.scenario_run_ids[scenario]
        first_edge_counts = {
            (
                edge.source_type,
                edge.source_public_id,
                edge.relation_type,
                edge.target_type,
                edge.target_public_id,
            ): edge.observation_count
            for edge in (await session.scalars(select(EntityEdge))).all()
        }
        first_customer_count = await session.scalar(select(func.count()).select_from(Customer))

        second = await generate_and_ingest(session, config, scenario=scenario)
        second_run_id = second.scenario_run_ids[scenario]

        assert (
            [event.canonical() for event in expected.events]
            == [event.canonical() for event in first.dataset.events]
            == [event.canonical() for event in second.dataset.events]
        )
        assert first.manifest.config_hash == second.manifest.config_hash
        assert first_run_id != second_run_id
        assert await session.scalar(select(func.count()).select_from(DatasetVersion)) == 1
        assert await session.scalar(select(func.count()).select_from(ScenarioRun)) == 2
        assert await session.scalar(select(func.count()).select_from(RawEvent)) == 160
        assert await session.scalar(select(func.count()).select_from(Transaction)) == 160
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 160
        second_customer_count = await session.scalar(select(func.count()).select_from(Customer))
        assert second_customer_count == first_customer_count

        raw_events = (await session.scalars(select(RawEvent))).all()
        assert len({raw.event_id for raw in raw_events}) == 160
        assert all(raw.payload["event_id"] == raw.event_id for raw in raw_events)
        audit_events = (await session.scalars(select(AuditEvent))).all()
        assert {audit.payload["event_id"] for audit in audit_events} == {
            raw.event_id for raw in raw_events
        }
        assert {audit.aggregate_id for audit in audit_events} == {
            transaction.public_id
            for transaction in (await session.scalars(select(Transaction))).all()
        }

        runs = (await session.scalars(select(ScenarioRun))).all()
        run_database_ids = {run.public_id: run.id for run in runs}
        transactions_by_run = {
            run_id: await session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.scenario_run_id == database_id)
            )
            for run_id, database_id in run_database_ids.items()
        }
        assert transactions_by_run == {first_run_id: 80, second_run_id: 80}

        second_edges = (await session.scalars(select(EntityEdge))).all()
        assert len(second_edges) == len(first_edge_counts)
        for edge in second_edges:
            key = (
                edge.source_type,
                edge.source_public_id,
                edge.relation_type,
                edge.target_type,
                edge.target_public_id,
            )
            assert edge.observation_count == first_edge_counts[key] * 2
