from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import get_settings
from packages.investigator import deterministic
from packages.investigator.domain import (
    GeneratedBy,
    InvestigationReport,
    LLMStatus,
)
from packages.investigator.evidence import EvidenceBuilder
from packages.investigator.provider import (
    DisabledProvider,
    InvestigatorProvider,
    ProviderUnavailableError,
    provider_from_config,
)


class InvestigatorService:
    def __init__(
        self,
        *,
        evidence_builder: EvidenceBuilder | None = None,
        provider: InvestigatorProvider | None = None,
        max_narrative_chars: int | None = None,
    ) -> None:
        settings = get_settings()
        self.evidence_builder = evidence_builder or EvidenceBuilder()
        self.provider = provider or provider_from_config(
            settings.investigator_provider, settings.openai_api_key
        )
        self.max_narrative_chars = max_narrative_chars or settings.investigator_max_narrative_chars

    async def investigate(self, session: AsyncSession, transaction_id: str) -> InvestigationReport:
        bundle = await self.evidence_builder.build(session, transaction_id)
        narrative = None
        generated_by = GeneratedBy.DETERMINISTIC
        llm_status = (
            LLMStatus.DISABLED
            if isinstance(self.provider, DisabledProvider)
            else LLMStatus.UNAVAILABLE
        )
        try:
            candidate = (await self.provider.generate(bundle)).strip()
            if not candidate or len(candidate) > self.max_narrative_chars:
                llm_status = LLMStatus.INVALID_RESPONSE
            else:
                narrative = candidate
                generated_by = GeneratedBy.LLM
                llm_status = LLMStatus.AVAILABLE
        except ProviderUnavailableError:
            pass
        except Exception:
            llm_status = LLMStatus.UNAVAILABLE

        return InvestigationReport(
            transaction_id=transaction_id,
            generated_by=generated_by,
            llm_status=llm_status,
            summary=deterministic.summary(bundle),
            decision_explanation=deterministic.decision_explanation(bundle),
            graph_narrative=deterministic.graph_narrative(bundle),
            narrative=narrative,
            evidence=bundle.evidence_items,
            related_entities=bundle.related_entities,
            cluster=bundle.cluster,
            timeline=bundle.timeline,
            recommended_next_step=deterministic.recommended_next_step(bundle),
            limitations=bundle.limitations,
            model=bundle.model,
            policy=bundle.policy,
            graph=bundle.graph,
            versions=bundle.versions,
            generated_at=datetime.now(UTC),
        )
