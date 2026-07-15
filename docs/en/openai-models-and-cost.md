# OpenAI models, data flow, and cost

[English](openai-models-and-cost.md) · [فارسی](../fa/openai-models-and-cost.md) · [Documentation](index.md)

OpenAI is optional for the synthetic demo and required only for uncached extraction or interpretive scoring in API mode.

## Data flow

Claim extraction sends selected video metadata, transcript hash, and the full line-numbered canonical transcript for that video. Scoring sends video metadata, structured claims, and structured outcome windows. Prompts instruct the model to return Pydantic-backed Structured Outputs. Requests set `store=false`; operators must verify current OpenAI platform documentation and their account terms rather than infer retention guarantees from this setting.

Do not submit content you are not permitted to process. Treat transcripts as untrusted prompt-injection input. Application validation checks video/claim IDs, line bounds, excerpt coverage, score/result consistency, trigger status, and data sufficiency.

## Models

Configure exact model IDs currently available to your account with `OPENAI_MODEL_CLAIM_EXTRACTION` and `OPENAI_MODEL_SCORING`. Record requested and returned model IDs. Do not use the word “latest” in a reproducibility record. A provider may retire a snapshot; preserve accepted response artifacts and hashes.

## Cost control

Paid stages require `AUDIT_MODE=api`, a runtime `OPENAI_API_KEY`, and `API_COST_ACKNOWLEDGED=true`. Begin with `--limit 1`, inspect usage, then set conservative concurrency. Optional price variables estimate accepted response cost from input, cached-input, and output tokens; failed calls may incur cost that local usage cannot observe. Verify prices on the official OpenAI site before every audit.

## Cache and reruns

Cache fingerprints include evidence, prompt, schema/policy, model, and reasoning settings. `--force` deliberately bypasses valid cache and can spend money. Identical inputs do not guarantee identical model language or judgment; reproducibility means preserving and verifying the accepted artifact, not promising deterministic re-generation.
