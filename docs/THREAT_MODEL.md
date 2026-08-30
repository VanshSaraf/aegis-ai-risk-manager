# Aegis Threat Model

## Scope

Aegis is a defensive system intended to identify coordinated payment abuse. It currently implements validated ingestion, synthetic data, point-in-time tabular features, point-in-time graph assessment, and deterministic structural cluster discovery. No trained AI model, final fraud prediction, policy automation, or investigator functionality is implemented.

## Data handling boundaries

- Domain references must be synthetic, tokenized, hashed, or fingerprinted identifiers.
- Aegis does not require or store card PAN or CVV.
- Names, email addresses, phone numbers, and full street addresses are outside the current data model.
- Ground-truth fields are reserved for synthetic training and evaluation data and are excluded from runtime scoring inputs.

## Capability boundaries

Aegis has no offensive capability. It does not generate attack instructions, probe payment systems, acquire credentials, or automate abuse. Current graph analysis and any future model components are intended only to analyze evidence already available to the defensive system.

The planned LLM investigator will be read-only, evidence-grounded, and outside the transaction decision path. It must not execute payment actions or override deterministic policy. No LLM integration currently exists.

This document will be expanded when model intelligence, deployment boundaries, authentication, and operational controls are designed.
