"""Deterministic synthetic payment-world generation for defensive evaluation."""

from packages.synthetic.config import GenerationConfig, load_generation_config
from packages.synthetic.generator import generate_dataset
from packages.synthetic.manifest import GenerationManifest, build_manifest
from packages.synthetic.validation import ValidationReport, validate_dataset

__all__ = [
    "GenerationConfig",
    "GenerationManifest",
    "ValidationReport",
    "build_manifest",
    "generate_dataset",
    "load_generation_config",
    "validate_dataset",
]
