# AI text-to-speech landscape and evaluation — research round 1

**Date:** 2026-10-11
**Method:** two exploratory web-research agents (Haiku 5.5, medium effort), about 30 searches total. Agent A covered the landscape (providers, open models, platforms, mediums, trends). Agent B covered evaluation, benchmarks and audiobook quality.
**Status:** exploratory, not verified by the parent session. Few claims were checked against primary pages (ACX policy, Kokoro license, Hugging Face Open TTS Leaderboard blog). Rankings and prices come mostly from secondary sources and change quickly. Use this as a map of topics, not as facts.

## Findings by theme

1. **Architecture.** Codec-token / LLM-style TTS dominates new models (Gemini TTS, gpt-4o-mini-tts, Fish, VibeVoice, Higgs). Style control moves to natural-language instructions and inline tags. Native multi-speaker dialogue is arriving (Gemini TTS, VibeVoice).
2. **Commercial vs open.** ElevenLabs, Google Gemini TTS and Cartesia trade first place on the Artificial Analysis listener-vote arena; snapshots disagree. Open-weight licenses are fragmenting: some new releases are non-commercial (Higgs Audio v3, reported) or keep the strongest variant hosted-only (Fish S1 vs S1-mini). Kokoro-82M is Apache-2.0 (confirmed on model card).
3. **Mediums.**

   | Medium | What dominates |
   |---|---|
   | Voice bots / customer service | Time-to-first-audio (target under about 200 ms, low confidence), streaming, telephony quality |
   | TikTok / short-form | Emotional range, fast iteration |
   | YouTube narration | Expressivity, editing control |
   | Film / TV dubbing | Lip-sync timing, actor consent |
   | Articles / news read-aloud | Volume, cost, clear neutral voice |
   | Audiobooks | Hours-long consistency, pronunciation, narration vs dialogue, platform policy; latency irrelevant |

   Shared across mediums: pronunciation control, text normalization, cost per hour, consent rules for cloned voices.
4. **Evaluation.** Human listening tests remain the reference: MOS (1–5 naturalness), CMOS (A vs B), MUSHRA. Cheap objective checks: WER/CER via ASR round-trip (catches skipped or mispronounced words, blind to prosody), speaker similarity (cloning only), UTMOS and other predicted-MOS models (weak at ranking strong systems), LLM-as-judge (EmergentTTS-Eval).
5. **Benchmarks.** Artificial Analysis Speech Arena (votes, commercial-heavy); Hugging Face Open TTS Leaderboard (launched 2026-09-30; WER, RTFx, time-to-first-audio, speaker similarity; Kokoro-82M reported among English WER leaders, rank not independently verified); Seed-TTS-eval (cloning-focused, scores vary by ASR used); EmergentTTS-Eval (NeurIPS 2025, expressive prompts); SwanBench-Speech (arXiv 2605.28618, May 2026, long-form consistency; abstract says models still lag on expressiveness over length).
6. **Audiobook quality ranking (agent B, most to least important):** pronunciation of recurring names; consistency over hours; pauses and narration-vs-dialogue differentiation; text normalization; emotion matched to text; listener fatigue; delivery specs (pass/fail gate); speaker similarity (cloning only); latency (irrelevant).
7. **Platforms and law.** ACX prohibits third-party AI narration unless authorized; only Amazon's Virtual Voice is accepted (ACX page updated 2026-04-15, confirmed by agent A). Spotify/Findaway and Apple Books accept labelled AI narration. ACX technical specs (third-party guides, official page not fetched): RMS −23 to −18 dB, peak ≤ −3 dB, noise floor ≤ −60 dB, MP3 192 kbps CBR 44.1 kHz. No official Apple Books audio spec found. EU AI Act Article 50: machine-readable marking of synthetic audio from 2026-08-02 (sources disagree on details; check the regulation text).

## Relevance to epub2audiobook

- Session #2 measured −22.2 LUFS with −0.2 dBFS peak. The peak would fail ACX's −3 dB limit. Not urgent for personal listening; a cheap fix under task `d0985e9d` (Audio quality quick wins).
- Local evaluation recipe for the open "listened quality" acceptance item: local Whisper transcription plus `jiwer` WER against source text; speaker-embedding drift over a 60-minute render; UTMOS as a trend line; `ffmpeg ebur128` loudness check; short blind A/B listen.
- v0.3 Spanish: one low-confidence source says Kokoro's Spanish voices sound English-accented. Test early (round 2, agent b).

## Gaps carried to round 2

- Pipeline best practices: LLM speaker attribution and emotion tagging, pronunciation dictionaries/SSML, multi-voice casting, long-form consistency techniques.
- About 15 models/providers not researched (F5-TTS, StyleTTS2, Azure, Polly, Hume and others).
- Spanish TTS: models, dialect choice, evaluation.
- Official ACX and Apple Books specification pages.

## Key sources

- ACX submission requirements (updated 2026-04-15): https://help.acx.com/s/article/what-are-the-acx-audio-submission-requirements
- Kokoro-82M model card: https://huggingface.co/hexgrad/Kokoro-82M
- Hugging Face Open TTS Leaderboard blog (2026-09-30): https://huggingface.co/blog/open-tts-leaderboard
- Artificial Analysis TTS leaderboard: https://artificialanalysis.ai/text-to-speech/leaderboard/provider-voice
- SwanBench-Speech (2026-05-27): https://arxiv.org/abs/2605.28618
- EmergentTTS-Eval (2025): https://arxiv.org/pdf/2505.23009
- TTSDS2 (2025): https://arxiv.org/pdf/2506.19441
- Qwen3-TTS report (2026-01): https://arxiv.org/pdf/2601.15621
- Seed-TTS-eval: https://github.com/BytedanceSpeech/seed-tts-eval
- Audible AI narration expansion, TechCrunch (2025-05-13): https://techcrunch.com/2025/05/13/audible-is-expanding-its-ai-narrated-audiobook-library/
- Spotify AI narration, Digital Music News (2025-02-21): https://www.digitalmusicnews.com/2025/02/21/spotify-audiobooks-ai-narration-support/
- Apple Books digital narration, Digital Music News (2023-01-05): https://www.digitalmusicnews.com/2023/01/05/apple-releases-catalog-of-ai-voiced-audiobooks/
- EU AI Act Article 50 note, CSA (2026-07-29): https://labs.cloudsecurityalliance.org/research/csa-research-note-eu-ai-act-article-50-transparency-20260729/
- Google Cloud TTS pricing: https://cloud.google.com/text-to-speech/pricing
