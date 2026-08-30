from typing import Protocol

from packages.investigator.domain import EvidenceBundle


class ProviderUnavailableError(RuntimeError):
    pass


class InvestigatorProvider(Protocol):
    async def generate(self, evidence: EvidenceBundle) -> str: ...


class DisabledProvider:
    def __init__(self, reason: str = "LLM investigator is disabled") -> None:
        self.reason = reason

    async def generate(self, evidence: EvidenceBundle) -> str:
        del evidence
        raise ProviderUnavailableError(self.reason)


def provider_from_config(provider_name: str, api_key: str | None) -> InvestigatorProvider:
    normalized = provider_name.strip().lower()
    if normalized == "disabled":
        return DisabledProvider()
    if normalized == "openai" and not api_key:
        return DisabledProvider("OPENAI_API_KEY is unavailable")
    return DisabledProvider(
        f"provider {provider_name!r} is not bundled; inject a read-only InvestigatorProvider"
    )
