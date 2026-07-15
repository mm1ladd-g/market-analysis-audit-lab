# Transcripts and language

[English](transcripts-and-language.md) · [فارسی](../fa/transcripts-and-language.md) · [Documentation](index.md)

## Source policy

Use a transcript only when collection, processing, model submission, storage, and intended publication are permitted. Public availability is not permission. Preferred sources are operator-owned captions, rights-holder-provided files, or another authorized export. The collector's platform adapter is gated by `SOURCE_RIGHTS_ACKNOWLEDGED` but the flag creates no legal right.

## Caption selection

`SUBTITLE_LANGUAGES` is ordered. Preserve whether a track is manual or automatically generated, its language tag, format, retrieval time, source metadata, and raw hash. Missing required subtitles are an evidence-based exclusion; never infer a transcript from a title.

## Normalization

Keep the raw caption beside a normalized UTF-8 text artifact. The manifest also writes a hashed `*.timing.json` sidecar that maps every canonical line to its SRT/VTT start and end time; authorized plain-text input carries explicit null timing. Normalize markup and repeated cue text conservatively; do not rewrite grammar or “polish” meaning before hashing evidence. Preserve Persian `ی`/`ک`, numbers as spoken where material, conditions, negation, and uncertainty. Any later edited reading copy is presentation only and must not replace canonical evidence.

## Audio transcription

Local or API speech-to-text is not a license to download third-party audio. The optional `transcribe` stage is disabled by default, runs only for in-scope videos from the validated YouTube channel, and canonicalizes each watch URL before download. Media subprocesses do not inherit the OpenAI key and have file, duration, and execution limits. The stage records model/settings, preserves segment timestamps, hashes input and output, and removes raw audio by default. Human corrections must remain separate from canonical machine output.

## Prompt injection and errors

Transcripts are untrusted. Text such as “ignore the audit rules” remains quoted evidence and must never override system instructions. Review low-quality audio, mixed languages, Persian/Arabic digit variants, named assets, negation, decimal separators, and timestamp drift. Exclude materially ambiguous claims rather than repair them silently.
