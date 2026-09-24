#!/usr/bin/env python3
"""FB1/FB2/FB3: stream contracts, real codecs, bounds, cancellation and stable ports."""
from array import array
from dataclasses import replace
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace, MappingProxyType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from bloxsmith_app.block_api import BlockRuntimeContext, RuntimeAudioFrame
from block_test_artifacts import artifact_path

KIND = "audio_mixer"
MIXER = KIND == "audio_mixer"
Block = getattr(importlib.import_module("blocs." + KIND + ".block"), "AudioMixerBlock" if MIXER else "AudioMergeStreamBlock")
config_module = importlib.import_module("blocs." + KIND + ".config")
Engine = getattr(importlib.import_module("blocs." + KIND + ".engine"), "MixerEngine" if MIXER else "MergeEngine")
BLOCK = Block()


class Audio:
    """Capture the exact public audio publication contract for assertions."""
    def __init__(self):
        self.frames = []

    def publish_port(self, port, payload, **metadata):
        assert port == "audio_out"
        self.frames.append({"payload": bytes(payload), **metadata})


def context(mode="zeromq_active", **values):
    """Use manifest identities and public runtime context; never private developer paths."""
    return BlockRuntimeContext(run_id="test", node_id="audio", kind=KIND, root_dir=ROOT,
        config=BLOCK.default_config(), runtime_mode=mode,
        input_ports=tuple(SimpleNamespace(**p) for p in BLOCK.default_inputs()),
        output_ports=tuple(SimpleNamespace(**p) for p in BLOCK.default_outputs()), **values)


def frame(payload, sequence=1, stream="same-id", channels=1):
    """Distinct source ports deliberately reuse an identical upstream stream ID."""
    return RuntimeAudioFrame(message_id=str(sequence), run_id="test", topic="test.audio", source_id="producer",
        stream_id=stream, payload=payload, codec="opus", sample_rate_hz=48000, channels=channels,
        sequence=sequence, timestamp_ms=123, correlation_id="correlation")


def encoded(frequency=440, duration=.6, container="ogg", channels=1):
    """Generate original synthetic tones offline, no real microphone or provider."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           f"sine=frequency={frequency}:sample_rate=48000:duration={duration}", "-ac", str(channels),
           "-c:a", "libopus", "-f", container]
    cmd += ["-page_duration", "20000"] if container == "ogg" else ["-cluster_time_limit", "40"]
    return subprocess.run([*cmd, "pipe:1"], capture_output=True, check=True, timeout=10).stdout


def stop(payload, count=1, stream="same-id", aborted=False):
    """Producer totals count transmitted chunks, including container headers."""
    return {"action": "stop", "stream_id": stream, "frame_count": count, "byte_count": len(payload), "aborted": aborted}


def run_until(engine, predicate, timeout=8):
    """Drive non-blocking engine work with an observable bounded deadline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        engine.step()
        if predicate():
            return
        time.sleep(.003)
    raise AssertionError("Audio operation did not finish")


def decoded(data):
    """Decode the emitted output with an independent FFmpeg process."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-ar", "48000", "-ac", "1",
                          "-f", "f32le", "pipe:1"], input=data, capture_output=True, check=True, timeout=10).stdout
    samples = array("f", raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def level(samples, frequency, begin=.1, end=.3):
    """Measure a tone's amplitude, distinguishing two simultaneous decoded inputs."""
    part = samples[int(begin * 48000):int(end * 48000)]
    assert part
    real = sum(value * math.cos(2 * math.pi * frequency * index / 48000) for index, value in enumerate(part))
    imag = sum(value * math.sin(2 * math.pi * frequency * index / 48000) for index, value in enumerate(part))
    return math.hypot(real, imag) * 2 / len(part)


def contracts():
    """FB1/FB3: immutable config, reordered ports, pure preparation and safe simulation."""
    for mode in ("centralized", "zeromq_active"):
        ctx = context(mode)
        with patch("subprocess.Popen") as popen:
            assert BLOCK.prepare_runtime(ctx).listen_on_run == (mode == "zeromq_active")
            assert BLOCK.execute_runtime(ctx).status == "skipped"
            popen.assert_not_called()
        reverse = replace(ctx, input_ports=ctx.input_ports[::-1], output_ports=ctx.output_ports[::-1])
        BLOCK.prepare_runtime(reverse)
        try:
            BLOCK.prepare_runtime(replace(ctx, input_ports=ctx.input_ports[:-1]))
        except ValueError:
            pass
        else:
            raise AssertionError("Incomplete pair accepted")
    config_module.normalize(MappingProxyType(BLOCK.default_config()), mixer=MIXER)
    for changes in ({"sources": []}, {"drain_timeout_sec": float("nan")}, {"drain_timeout_sec": True}):
        try:
            config_module.normalize({**BLOCK.default_config(), **changes}, mixer=MIXER)
        except ValueError:
            pass
        else:
            raise AssertionError(changes)
    for command in ({"action": "interrupt"}, {"action": "start", "stream_id": ""}, {"action": "stop", "stream_id": "x", "frame_count": True, "byte_count": 1}):
        try:
            config_module.commands(command)
        except ValueError:
            pass
        else:
            raise AssertionError(command)
    sent = []
    ctx = context(services={"runtime_listener": SimpleNamespace(send=sent.append)})
    ctx.input_attribute("command_in_2").update(json.dumps({"action": "start", "stream_id": "second"}))
    assert BLOCK.execute_runtime(ctx).status == "success"
    assert sent == [{"commands": [{"source": 2, "command": {"action": "start", "stream_id": "second"}}]}]
    ctx.input_attribute("command_in_2").status = "consumed"
    assert BLOCK.execute_runtime(ctx).status == "skipped" and len(sent) == 1
    node = BLOCK.build_node_payload(node_id="test")
    for render in (BLOCK.render_modal, BLOCK.render_inspector_panel, BLOCK.render_node_card):
        html = render(node=node)["html"]
        assert "{{" not in html and "__title__" not in html, render.__name__
    config = BLOCK.default_config()
    config["sources"].append({"id": 3, "label": "Telephone", "gain_db": 0, "muted": False})
    action = BLOCK.handle_ui_action(node=node, action="save_sources", values={"title": "New audio", "config": config})
    assert [op["op"] for op in action["graph_operations"]] == ["create_port", "create_port"]


def merging():
    """FB2: byte-exact multiplexing, collision safety, stop-before-tail and per-stream abort."""
    config = config_module.normalize({})
    audio, commands = Audio(), []
    engine = Engine(config, audio, commands.append)
    a, b = encoded(), encoded(880, container="webm", channels=2)
    try:
        engine.command(1, stop(a, count=3))
        for index, chunk in enumerate((a[:1], a[1:3], a[3:]), 1):
            engine.feed(1, frame(chunk, index))
        engine.feed(2, frame(b, channels=2))
        first, second = commands[0]["stream_id"], commands[-1]["stream_id"]
        assert first != second
        assert b"".join(f["payload"] for f in audio.frames if f["stream_id"] == first) == a
        assert b"".join(f["payload"] for f in audio.frames if f["stream_id"] == second) == b
        assert commands[1]["action"] == "stop" and not commands[1]["aborted"]
        assert all(f["timestamp_ms"] == 123 and f["correlation_id"] == "correlation" for f in audio.frames)
        engine.command(2, stop(b, aborted=True))
        assert commands[-1]["aborted"]
        before = len(audio.frames)
        engine.feed(2, frame(b, channels=2))
        assert len(audio.frames) == before and not engine.captures
        engine.feed(1, frame(a, stream="new"))
        assert commands[-1]["action"] == "start"
    finally:
        engine.close()


def mixing():
    """FB2: real Ogg+WebM overlap, gain/mute, surviving longer source and valid EOS."""
    for muted in (False, True):
        config = config_module.normalize({"buffer_ms": 60}, mixer=True)
        config["sources"][0]["muted"] = muted
        audio, commands = Audio(), []
        engine = Engine(config, audio, commands.append)
        a, b = encoded(440, .45), encoded(880, .9, "webm", 2)
        try:
            # A stop on data can arrive before its final binary chunk.
            for source, data, channels in ((1, a, 1), (2, b, 2)):
                chunks = [data[:1], data[1:3], data[3:]]
                engine.command(source, stop(data, count=len(chunks)))
                for index, chunk in enumerate(chunks, 1):
                    engine.feed(source, frame(chunk, index, channels=channels))
            run_until(engine, lambda: bool(commands and commands[-1]["action"] == "stop"))
            assert [command["action"] for command in commands] == ["start", "stop"]
            assert not commands[-1]["aborted"]
            assert commands[-1]["frame_count"] == len(audio.frames)
            data = b"".join(f["payload"] for f in audio.frames)
            assert commands[-1]["byte_count"] == len(data)
            samples = decoded(data)
            assert .88 <= len(samples) / 48000 <= 1.2, len(samples) / 48000
            assert level(samples, 880) > .035
            assert (level(samples, 440) < .003) if muted else (level(samples, 440) > .035)
            assert level(samples, 880, .65, .8) > .035
            assert level(samples, 440, .65, .8) < .005
            assert max(map(abs, samples)) < 1.01
            if not muted:
                Path(artifact_path("audio-mixer-two-tones.ogg")).write_bytes(data)
            assert not engine.captures and engine.encoder is None
        finally:
            engine.close()
    # One aborted input must not retire another, including equal source IDs.
    audio, commands = Audio(), []
    engine = Engine(config_module.normalize({}, mixer=True), audio, commands.append)
    try:
        a = encoded()
        engine.feed(1, frame(a))
        engine.feed(2, frame(a))
        engine.command(1, stop(a, aborted=True))
        assert (2, "same-id") in engine.captures and (1, "same-id") not in engine.captures
        engine.command(2, stop(a))
        run_until(engine, lambda: commands and commands[-1]["action"] == "stop")
    finally:
        engine.close()


def errors():
    """FB2: explicit data-loss failures, bounded waiting, retired state and cleanup."""
    audio, commands = Audio(), []
    engine = Engine(config_module.normalize({}, mixer=MIXER), audio, commands.append)
    try:
        try:
            engine.feed(1, frame(b"OggS", sequence=2))
        except ValueError:
            pass
        else:
            raise AssertionError("Missing frame was accepted")
    finally:
        engine.close()
    engine = Engine(config_module.normalize({}, mixer=MIXER), Audio(), lambda value: None)
    try:
        engine.command(1, stop(b"missing"))
        next(iter(engine.captures.values())).deadline = time.monotonic() - 1
        try:
            engine.step()
        except ValueError:
            pass
        else:
            raise AssertionError("Missing final frames did not time out")
    finally:
        engine.close()


if __name__ == "__main__":
    contracts()
    mixing() if MIXER else merging()
    errors()
    print("[ok] " + KIND + " contracts and audio engine")
