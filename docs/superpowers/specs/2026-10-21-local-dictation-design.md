# Local Dictation (Ctrl+Shift+Space) Design

Date: 2026-10-21
Branch: `feat/local-dictation` (from `main`)

## Problem

Dictation (the mic button and Ctrl+Shift+Space) uses the browser Web Speech API. In Electron that API exists but always fails with `error:network`, because Electron ships no Google speech backend. `web/static/speech.js` ignores the error and restarts recognition in a loop, so dictation does nothing and gives no feedback.

## Goals

- Dictation works in the Electron app with no network access and no external server (no Lemonade dependency).
- Speech recognition runs locally in the Python backend.
- The model is bundled in the installer and can be swapped without changing client or route code.
- No NVIDIA-only models or runtimes. Users on AMD hardware must not be affected.
- English only.
- A failed engine surfaces a visible error instead of looping silently.

## Non-goals

- Streaming partial (interim) text while the user is still speaking.
- Languages other than English.
- GPU acceleration. CPU inference only.
- Replacing the Lemonade-based TTS used by the Demo Recorder.

## Reference: Lemonade

Lemonade captures microphone audio in the page, converts it to 16 kHz mono PCM16, streams it over a WebSocket to a local server, and transcribes with Whisper (whisper.cpp) or Moonshine. It keeps a model registry with per-model metadata and defaults to a small model.

This design keeps the capture format, the registry idea and the small default. It differs in two ways:

- **Transport:** one HTTP POST per utterance instead of a WebSocket. All state-changing HTTP routes in this app sit behind `verify_csrf`; a WebSocket would add an unguarded endpoint that accepts microphone audio.
- **Engine:** faster-whisper (CTranslate2) in-process, instead of a separate server.

## Architecture

```
mic -> getUserMedia -> AudioWorklet -> 16 kHz mono PCM16 frames
    -> segmenter (energy VAD) -> one utterance (Int16 PCM)
    -> POST /api/dictation/transcribe (X-CSRF-Token)
    -> engine.transcribe(pcm) -> text
    -> existing insertFn (field / Quill inserters)
```

### Units

| Unit | Responsibility |
|---|---|
| `web/static/speech-capture.js` + `web/static/speech-worklet.js` | Open the mic at 16 kHz, produce mono PCM16, segment utterances, call a callback per utterance. No DOM, no network. |
| `web/static/speech.js` (edited) | Keeps `GatorSpeech` API, hotkey, registry, inserters, toasts and stop-on-send. Replaces the `SpeechRecognition` block with the capture unit plus a POST of each utterance. |
| `web/dictation/engine.py` | `Engine` interface: `load(model_dir)` and `transcribe(pcm16: bytes) -> str`; engine registry keyed by name. |
| `web/dictation/faster_whisper_engine.py` | The faster-whisper adapter (the only engine in this change). |
| `web/dictation/models.json` | Model manifest (see Model registry). |
| `web/dictation/service.py` | Resolves the active model, locates its directory, lazily loads the engine once, serializes calls. |
| `web/routes/dictation.py` | The HTTP route. Registered in `web/app.py` with `include_router`. |
| `tools/fetch_dictation_model.py` | Build-time download of the pinned model with checksum verification. |

The `GatorSpeech` public API (`wire`, `isSupported`, `stopAll`, `makeFieldInserter`, `makeQuillInserter`, etc.) does not change, so `index.html` and `third-pane.js` are untouched.

## Page side

### Capture

- `navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })`.
- The `AudioContext` is created at `sampleRate: 16000`, so the browser resamples the mic and no downsampler is needed. Capture fails with a clear error if the context does not run at 16 kHz.
- An `AudioWorklet` (module loaded from `/static`, zero outputs) posts Float32 blocks to the page, which converts them to PCM16.
- `isSupported()` becomes: `getUserMedia` and `AudioWorklet` are available.

### Segmenter

Energy-based VAD over 20 ms frames, all thresholds as named constants at the top of `speech-capture.js`:

- Speech starts after 3 consecutive frames above the RMS threshold; 300 ms of pre-roll audio is included.
- An utterance ends after 700 ms of silence.
- Utterances shorter than 250 ms of speech are dropped.
- An utterance is force-cut at 20 s and a new one begins.
- The mic keeps running between utterances until the user stops dictation or sends the message.

The backend also runs VAD, so an energy false-trigger yields empty text, not junk.

### Session behavior

- One in-flight transcription per session; utterances queue in order and their text is inserted in order.
- On a CSRF 403 the client refreshes its token and retries once (the same pattern as the narration approval fix).
- On 503, 413, a network failure, or `getUserMedia` denial: the session stops, the mic is released, and a toast states the reason. No automatic restart.
- While the first request is pending and the model is loading, the mic button shows a "preparing" state.

## Backend

### Route

`POST /api/dictation/transcribe`, declared with `dependencies=[Depends(verify_csrf)]`.

- Request body: raw bytes, `Content-Type: application/octet-stream`, PCM16 little-endian, mono, 16 kHz.
- Body length must be even (else 400) and at most 20 s of audio, 640,000 bytes (else 413). Empty body returns `{"text": ""}`.
- Response: `{"text": "<transcript>"}` (trimmed; empty string when no speech).
- 503 with `{"detail": "..."}` when the model is missing or fails to load.
- Audio is held in memory only, never written to disk, never logged. Logs contain duration and elapsed time, not content.

### Service and engine

- The service loads the engine on the first request and keeps it for the process lifetime. Loads are guarded by a lock; a failed load is retried on the next request.
- `transcribe` runs in a worker thread (`run_in_executor`) so the event loop stays free, and calls are serialized with a lock.
- faster-whisper settings: `device="cpu"`, `compute_type="int8"`, `language="en"`, `beam_size=5`, `vad_filter=True`. PCM16 is converted to float32 in `[-1, 1)` and passed as an array, so no audio file decoding happens.

## Model registry

`web/dictation/models.json`:

```json
{
  "default": "base.en",
  "models": {
    "base.en": {
      "engine": "faster-whisper",
      "dir": "faster-whisper-base.en",
      "repo": "Systran/faster-whisper-base.en",
      "revision": "<pinned commit sha>",
      "license": "MIT",
      "size_mb": 145,
      "files": { "model.bin": "<sha256>", "config.json": "<sha256>", "tokenizer.json": "<sha256>", "vocabulary.txt": "<sha256>" }
    }
  }
}
```

- The active model is `config.json` key `dictation.model`, falling back to the manifest `default`. An unknown id returns 503 with the list of known ids.
- Model directories are searched in order: `~/.gator/models/dictation/<dir>` (user override, no rebuild needed), then `$AIGATOR_MODELS_DIR/<dir>`.
- Swapping to another model on the same engine: add a manifest entry and place the files. Adding a new engine (for example Moonshine): add one adapter file registered under a new engine name. Client and route are unchanged.

## Packaging

- `tools/fetch_dictation_model.py` downloads the manifest's active model at the pinned revision into `models/dictation/<dir>/` and fails the build on any SHA-256 mismatch. `models/` is gitignored.
- `shell/package.json` `extraResources` gains `{ "from": "../models/dictation", "to": "models/dictation" }`.
- `shell/main.js` sets `AIGATOR_MODELS_DIR` to `<resourcesPath>/models/dictation` in the backend environment when packaged, and to `<repo>/models/dictation` in development.
- `faster-whisper==1.2.1` is added to `web/requirements.txt` and `pyproject.toml`; `uv.lock` resolves its dependencies (`av`, `ctranslate2`, `onnxruntime`, `numpy`). `av` is imported at module load by faster-whisper and stays in the bundle. Only the array path is used (PCM bytes to numpy), so faster-whisper's file-open path, which fails with some `av` versions, is never reached.
- `packaging/aigator-backend.spec` adds `collect_all` for `faster_whisper`, `ctranslate2` and `onnxruntime` (the Silero VAD model ships as a faster-whisper data file).
- Third-party notices list Whisper (MIT), the CTranslate2 conversion, faster-whisper (MIT) and CTranslate2 (MIT).

## Security

- The route is protected by `verify_csrf`; no entry is added to `tests/csrf_route_baseline.txt`.
- No new WebSocket. No outbound network use at runtime.
- The AudioWorklet module is a same-origin static file, served from `/static`.
- Request size is capped before any processing.

## Error handling summary

| Condition | Result |
|---|---|
| Mic permission denied / no device | Toast, session stops |
| Model missing or fails to load | 503, toast with reason, session stops |
| Bad length (odd bytes) | 400 |
| Over 20 s of audio | 413 |
| CSRF 403 | Refresh token, retry once, then toast and stop |
| No speech detected | `{"text": ""}`, nothing inserted |

## Testing

- **Python route tests** (fake engine registered in tests): 403 without a CSRF token; 400 for odd length; 413 for oversize; 200 with text from the fake engine; 503 when the engine fails to load; engine is loaded once across calls.
- **Registry tests:** manifest default resolves; `dictation.model` override resolves; unknown id gives a clear error listing known ids; user-override directory wins over the bundled directory.
- **JS tests** (`tests/*.test.js` pattern): the segmenter (start threshold, silence hangover, minimum speech, force cut, pre-roll) and the float-to-PCM16 conversion, fed synthetic PCM.
- **Real-model test:** transcribes a short fixture WAV with the bundled model; skipped when the model directory is absent.
- **Manual end-to-end in Electron:** launch with Chromium's `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>`, press Ctrl+Shift+Space in a text field, confirm text appears; repeat with the backend model removed and confirm a toast and a stopped session.

## Open items (resolved before release, no design change)

- Pre-release evaluation of candidate models on recorded dictation (base.en, distil-small.en, Moonshine small); the winner becomes the manifest `default`.
- Measure the installer size delta.
- Confirm the macOS build path (`extraResources`, wheels for arm64).
