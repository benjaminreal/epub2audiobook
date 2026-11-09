# AI text-to-speech research — round 2: pipeline, Spanish, open-model shortlist

**Date:** 2026-10-11
**Method:** three web-research agents (Haiku 5.5, high effort), about 190 tool calls. Agent a: pipeline best practices. Agent b: Spanish TTS. Agent c: open-weight model shortlist. Agents were told to confirm key claims on primary pages and to label confidence.
**Status:** licences, repositories and GitHub issues were mostly confirmed on primary pages. Rankings, speeds and quality claims are mostly secondary or vendor self-reports. The parent session verified only the chunking check below.
**Dev machine (read 2026-10-11 with `system_profiler`):** Mac Studio (Mac14,13), Apple M2 Max, 12 CPU cores (8 performance, 4 efficiency), 30-core GPU, 32 GB RAM, macOS 27.0.1.
**Previous round:** `tts_landscape_round1.md`.

## Verified in our code

- **ONNX default path does not truncate long text.** The installed `kokoro-onnx` splits phonemes into batches of at most 510 (`kokoro_onnx/chunker.py`, `config.py: MAX_PHONEME_LENGTH = 510`), so the engine's 2,000-character chunks are safe. Checked by reading the installed package source, not by a test run.
- **MLX path not checked.** It goes through `mlx-audio`. Check by comparing input length with audio duration on one long paragraph.

## Pipeline best practices (agent a)

**Adopt now**
- A logged text-normalization pass with a per-book rule file; do not rely on the model's front-end.
- A per-book, case-sensitive pronunciation lexicon (W3C PLS format for portability). Kokoro's inline `[word](/IPA/)` syntax belongs to its `misaki` front-end; our ONNX path phonemizes with espeak-ng, so a lexicon would need phoneme substitution (`kokoro-onnx` accepts phoneme input). Not yet verified.
- Sentence-level segments with stable IDs and a manifest, so single segments can be regenerated (the AI equivalent of a narrator's pickup).
- Automated QC: ASR round-trip diff against the source text, used as a review queue of deletions and insertions, not a pass/fail score (one paper reports about 95% recall and 49% precision for this kind of flagging). Clean Whisper output of hallucinated loops before scoring.
- ACX gate (confirmed on the ACX page by agent a): RMS −23 to −18 dB per file, peaks ≤ −3 dB, noise floor ≤ −60 dB RMS, MP3 ≥ 192 kbps CBR 44.1 kHz, 1–5 s room tone at start and end, ≤ 120 min per file, one chapter per file. Whether ACX measures RMS or LUFS is disputed between sources.

**Later**
- LLM speaker attribution with a verification pass against the source (NAACL 2025: Llama-3 beat ChatGPT and encoder baselines on quotation attribution across 28 novels).
- Narrator plus one dialogue voice; full cast only once attribution is verified. The only listener-preference evidence for multi-cast narration is commissioned by a multi-cast vendor (Spoken).
- EPUB3 read-along export.

**Avoid for now:** free-form emotion tags (Kokoro has no tag control); trusting the out-of-dictionary fallback without testing; long crossfades; auto-accepting QC flags.

**Comparable open-source projects:** audiobook-creator (GPL-3.0, Kokoro, LLM attribution and emotion tags), autiobook (GPL-3.0, LLM cast/script/revise), audiblez (MIT, Kokoro, single voice), ebook2audiobook (Apache-2.0, XTTS and others), Calliope (arXiv 2602.10735, sentence-level synthesis with 50 ms fade and 0.15 s silence).

## Spanish (agent b)

- **Kokoro has three Spanish voices** (`ef_dora`, `em_alex`, `em_santa`) with **no published grade**. Open issue hexgrad/kokoro#246 reports Latin American pronunciation; there is no Castilian voice.
- **espeak-ng `es` produces Castilian phonemes (θ); `es-419` produces Latin American ones.** Pairing Latin American voices with Castilian phonemes may sound inconsistent. This is an inference to test by listening.
- **Open bugs to watch:** #301 (em_alex silent on Windows), #364 (Italian voices cut to 0.3 s on an M1 Mac through the same espeak route; not reported for Spanish).
- **espeak-ng 1.52.0 normalization, local test by agent b.** Correct: "1.250", "3,5", "25%", "5 €", "1999", "Sr.", "Sra.", "Dra.", "Ud.", "un águila". Wrong: "2 h" (dos hache), "km/h" (barra hache), "1.º" (uno punto o), "11/10/2026" (slashes read), "p. m.", "USD", "Lcdo.", "EE. UU." (spelled out). The dialogue raya (—) is dropped.
- **Front-end checklist (15 rules, summarised):** units; gendered ordinals; dates; times (a. m., p. m.); currency codes; per-book decimal and thousands separator setting; abbreviation map; acronym list; policy for English names; test whether ¿ ¡ affect prosody; split dialogue turns at the raya before G2P, with a short pause between turns; split speaker tags ("—dijo ella—") into their own segment; articles before stressed a-; « » quotes; sentence chunks of 100–200 tokens (Kokoro's VOICES.md says quality drops below 10–20 tokens and rushes above about 400).
- **Licence:** espeak-ng is GPL-3.0; the project is already GPL-3.0-or-later for that reason.
- **Fallbacks:** Chatterbox multilingual (MIT; separate es-es and es-mx-latam packs; avoids espeak), Qwen3-TTS (Apache-2.0; self-reported Spanish WER/SIM vs ElevenLabs), Piper es_MX "claude" (Apache-2.0 voice; same espeak front-end).
- **Spanish ASR for WER:** Whisper large-v2 scores 3.0% WER on FLEURS Spanish (Whisper paper, Table 13); the large-v3 figure was not verified.
- **Dialect policy of publishers:** no primary source found. Default assumption: match voice to author's origin, as a per-book setting.

**30-minute Kokoro Spanish test plan (agent b):** 12 test lines (plain, dialogue with rayas, numbers/units/dates, abbreviations, an English name, one 150-token paragraph); render with all three voices; blind 1–5 scores for naturalness and accent; mechanical checks for silence, duration vs character count, and truncation; optional Whisper WER. Go criteria: no silent or truncated output, at least one voice averaging ≥ 3.5, errors covered by fewer than about 10 normalization rules.

## Open-model shortlist (agent c)

- Hugging Face Open TTS Leaderboard (2026-09-30), per a secondary write-up: Kokoro-82M is #1 on English WER (1.46). RTFx there is measured on an H200 GPU, not comparable to Mac numbers.
- **Shortlist for an A/B against Kokoro (permissive licences, Spanish listed):**
  1. Qwen3-TTS 0.6B/1.7B — Apache-2.0, cloning, in mlx-audio; vendor numbers suggest roughly 4–5× slower than Kokoro.
  2. Chatterbox multilingual — MIT, cloning and emotion control, in mlx-audio; no Apple speed data.
  3. Fun-CosyVoice3-0.5B — Apache-2.0, best self-reported Spanish WER among permissive models (4.25% on CV3-Eval); not in mlx-audio.
- **Excluded for licence (non-commercial or research-only):** Fish S2 Pro, Voxtral TTS, OmniVoice, Higgs v3, Breeze TTS 2, F5-TTS/E2, XTTS-v2, Spark-TTS, MaskGCT. **Unresolved licence:** Kani-TTS, MegaTTS3, IndexTTS-2.5. **Use restrictions:** Supertonic-3 (OpenRAIL-M; GPL compatibility unanswered). **No Spanish:** VibeVoice, Zonos, CSM, Dia2, Orpheus, Parler, StyleTTS2, NeuTTS-Air.

## Recommendation

Stop researching; the remaining questions are about sound and need local listening tests. Run the Spanish Kokoro test first; run the alternative-model A/B only if it fails. Fold the ASR round-trip and ACX checks into the audio quality task.

## Key sources

- Kokoro VOICES.md: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
- Kokoro pipeline: https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py
- Kokoro issues: https://github.com/hexgrad/kokoro/issues/246, /301, /364
- misaki: https://github.com/hexgrad/misaki
- espeak-ng languages: https://github.com/espeak-ng/espeak-ng/blob/master/docs/languages.md
- ACX audio requirements: https://help.acx.com/s/article/acx-audio-submission-requirements
- ElevenLabs pronunciation dictionaries: https://elevenlabs.io/docs/eleven-api/guides/how-to/text-to-speech/pronunciation-dictionaries
- Azure SSML pronunciation (2026-02-25): https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-pronunciation
- Calliope (2026-02-11): https://arxiv.org/html/2602.10735v1
- Quotation attribution with LLMs (NAACL 2025): https://aclanthology.org/2025.naacl-short.62
- Whisper hallucination study (2025-01): https://arxiv.org/html/2501.11378v1
- Open TTS Leaderboard (2026-09-30): https://huggingface.co/blog/open-tts-leaderboard ; secondary results: https://www.creativeainews.com/articles/open-tts-leaderboard-license-cpu-test-2026/
- mlx-audio: https://github.com/Blaizzy/mlx-audio
- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS ; report: https://arxiv.org/pdf/2601.15621
- Chatterbox: https://huggingface.co/ResembleAI/chatterbox
- Fun-CosyVoice3: https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 ; CV3-Eval: https://arxiv.org/html/2505.17589v2
- Piper voices: https://huggingface.co/rhasspy/piper-voices
- Spanish TTS MOS study (2025): https://arxiv.org/abs/2507.01805
- Projects: https://github.com/prakharsr/audiobook-creator , https://github.com/khimaros/autiobook , https://github.com/santinic/audiblez , https://github.com/DrewThomasson/ebook2audiobook
