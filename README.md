# Audio Mixer

<!-- block-metadata:start -->
[![Block version: 0.1.0](https://img.shields.io/badge/block-0.1.0-blue)](model.json)
[![BloxSmith compatibility: 1.0.9](https://img.shields.io/badge/BloxSmith-1.0.9-brightgreen)](compatibility.json)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Verified BloxSmith versions: **1.0.9** (bundled-block tests; see [test evidence](compatibility.json)).
<!-- block-metadata:end -->

[![Audio Mixer — amber pixel-art module mixing multiple waveforms into one](media/thumbnail.webp)](media/cover.png)

*Concept illustration of the block's function, not a Studio screenshot. [Artwork and generation prompt](media/README.md).*

## Role

Mix independently decoded Opus sources into one new, clocked Ogg/Opus stream. Each source has its own gain and mute setting. Stopping or aborting one source leaves the others active.

## Wiring

Each source has a visible pair: `audio_in_N` (audio) and `command_in_N` (JSON).
Connect both outputs of Microphone Stream, Telephony or OpenAI TTS Stream to the
same numbered pair. A port accepts one link. Two default pairs remain present;
**Add a source** creates more pairs, up to eight, using stable IDs.

Outputs are `audio_out` and `command_out`; commands never travel implicitly
inside the audio link. Connect both to Save Audio or a compatible consumer.
The output is one newly identified mixed stream. It does not retain speaker identities.

Opus/WebM and Opus/Ogg, mono or stereo, are decoded internally to 48 kHz floating-point PCM, mixed and encoded as Ogg/Opus. The graph format remains Opus.

## Lifecycle and limits

Listening starts at **Run**, without Play or a data trigger. The first audio chunk
can precede start. Producer commands are separate JSON messages:

```json
{"action":"start","stream_id":"capture"}
{"action":"stop","stream_id":"capture","frame_count":12,"byte_count":32000,"aborted":false}
```

A batch may contain 1–64 commands. Only fresh deliveries are interpreted. Stop can
arrive before the final audio: counts include every chunk and container header.
A non-aborted stop is successful only after exact totals are reconciled.
An aborted source is retired without stopping other sources. Missing/duplicated
frames, changing profiles, malformed commands and saturated buffers fail visibly.
Global interruption commands or VAD begin/commit events are not producer lifecycle
commands and must not be connected here.

There are at most 16 open captures and 256 retired identities per Run. Producers
must use fresh IDs within a Run. Always connect producer commands for clean
completion; network inactivity never proves completion. Downstream limits remain
independent: the current VAD accepts at most **four open captures**.

A 20 ms output clock aligns sources by local arrival, not synchronized hardware
sample clocks. A configurable startup margin (150 ms by default) absorbs decoder
startup differences. Late decoded samples are retained, not discarded as missing
first words. This is live voice mixing, not studio sample-accurate synchronization
or echo cancellation. Every capture has a two-second decoded PCM buffer and a
bounded encoded queue. The output ends only after every capture and the encoder
have drained. Input abort cuts that source, not the entire mixed recording.

Source gain is −60 to +6 dB; mute still consumes the source so queues cannot grow.
Master gain defaults to −6 dB for two-source headroom. A peak-safe PCM limiter
prevents summed sample overload; it is not an acoustic loudness normalizer.
The Opus output may have codec reconstruction overshoot. Output is mono by default,
with stereo available. FFmpeg with libopus must already be installed on the host.
No installation, device capture or network request is performed by this block.

Processing errors abort unfinished output when possible. Runtime Stop revokes
services and promptly releases local resources; it cannot guarantee delivery of a
final business stop. **One Shot Simulation skips continuous audio**, opens no
codec or device and emits no lifecycle commands.

## Properties and ergonomics

The modal and inspector expose the same source editor: source names, visible
audio/command pairing, gain and mute, and progressively disclosed advanced settings.
Every change stays local until **Apply**. **Reset draft** or closing the modal
discards unsaved changes. Close and Apply remain reachable at narrow sizes.
Rename preserves port IDs and links. Added sources can be removed only after
disconnecting their links; the block never silently deletes a connection.
The two default sources cannot be removed; leave an unused pair unconnected.

Ports are managed exclusively as pairs in this editor, instead of offering an
independent generic Ports editor that could break their association.
Changes require **Stop, then Run**; mixer sliders/settings are not live controls.
Properties are release-scoped ES modules with English and French catalogs.
The compact canvas card summarizes the role and source names.

## Files and tests

- `block.py`: public lifecycle hooks and behavior markers.
- `config.py`: source/command validation and stable port identities.
- `runtime.py`: fair bounded listener and explicit command hand-off.
- `engine.py`: independent codecs, PCM mixing, output pacing and cleanup.
- `ui.py`, templates, `assets/`, `locales/`: owned draft editor and translations.
- `tests/`: portable tests using synthetic audio and disposable framework instances.

From the private integration workspace:

```sh
python3 -B tests/run_tests.py audio_mixer
```

Tests use no real microphone, telephone or paid provider. Public block tests do not
bundle the proprietary framework. Compatibility evidence is maintained by
HackInvent in `compatibility.json`; a local passing run is not a published release.

The suites cover managed and linked packages, real HTTP/WebSocket audio routes
to Save Audio, overlapping Ogg/WebM tones, live output before Stop, successive
captures, independent stereo channels, mute/gain/limiting, bounded buffers and
codec cleanup. Browser checks exercise modal and inspector drafts, paired-port
editing, English/French catalogs and layouts from 320 px to desktop.

## License

Apache-2.0. FFmpeg is an external system dependency for Audio Mixer and is not bundled.
