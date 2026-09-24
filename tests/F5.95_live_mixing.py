#!/usr/bin/env python3
"""FB2/FB3: output before Stop, independent stereo, gain, limiter and codec cleanup."""
from array import array
from pathlib import Path
import runpy
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from blocs.audio_mixer.engine import MixerEngine, InputCapture, RATE, SAMPLES
from blocs.audio_mixer.config import normalize, MAX_BUFFER, MAX_STREAMS

F = runpy.run_path(str(Path(__file__).with_name("F5.92_audio_engine.py")))


def ogg_pages(data):
    """Split the original container at page boundaries, without rewriting packets."""
    offset = 0
    while offset < len(data):
        assert data[offset:offset + 4] == b"OggS"
        header = 27 + data[offset + 26]
        size = header + sum(data[offset + 27:offset + header])
        yield data[offset:offset + size]
        offset += size
    assert offset == len(data)


def live_and_reuse():
    """Clock incoming pages like a live producer; Stop cannot unlock first output."""
    audio, commands = F["Audio"](), []
    engine = MixerEngine(normalize({"buffer_ms": 60}, mixer=True), audio, commands.append)
    data = F["encoded"](440, 1.2)
    pages = list(ogg_pages(data))
    try:
        engine.command(1, {"action": "start", "stream_id": "live"})
        first = time.monotonic()
        for index, page in enumerate(pages, 1):
            engine.feed(1, F["frame"](page, index, "live"))
            until = first + max(0, index - 2) * .02
            while time.monotonic() < until:
                engine.step()
                time.sleep(.002)
        assert len(audio.frames) > 3, "Mixer buffered the whole capture instead of streaming"
        assert [c["action"] for c in commands] == ["start"]
        engine.command(1, F["stop"](data, len(pages), "live"))
        F["run_until"](engine, lambda: commands[-1]["action"] == "stop")
        samples = F["decoded"](b"".join(f["payload"] for f in audio.frames))
        assert F["level"](samples, 440) > .045
        assert 1.18 <= len(samples) / RATE < 1.6
        old_id = commands[-1]["stream_id"]
        first_count = len(audio.frames)
        next_data = F["encoded"](880, .3, "webm", 2)
        engine.feed(2, F["frame"](next_data, 1, "next", 2))
        engine.command(2, F["stop"](next_data, stream="next"))
        F["run_until"](engine, lambda: len(commands) == 4)
        assert commands[-1]["stream_id"] != old_id and not commands[-1]["aborted"]
        assert all(f["stream_id"] != old_id for f in audio.frames[first_count:])
        assert not engine.captures and engine.encoder is None
    finally:
        engine.close()


def stereo():
    """Use different left/right tones to catch accidental stereo-to-mono conversion."""
    data = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "aevalsrc=0.2*sin(2*PI*440*t)|0.2*sin(2*PI*880*t):s=48000:d=0.7",
        "-c:a", "libopus", "-f", "ogg", "pipe:1"], capture_output=True, check=True, timeout=10).stdout
    audio, commands = F["Audio"](), []
    engine = MixerEngine(normalize({"channels": 2, "buffer_ms": 60}, mixer=True), audio, commands.append)
    try:
        engine.feed(1, F["frame"](data, channels=2))
        engine.command(1, F["stop"](data))
        F["run_until"](engine, lambda: commands and commands[-1]["action"] == "stop")
        assert all(f["channels"] == 2 for f in audio.frames)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "f32le", "pipe:1"],
            input=b"".join(f["payload"] for f in audio.frames), capture_output=True, check=True, timeout=10).stdout
        values = array("f", raw)
        if sys.byteorder != "little":
            values.byteswap()
        left, right = values[::2], values[1::2]
        assert F["level"](left, 440) > .06 and F["level"](left, 880) < .005
        assert F["level"](right, 880) > .06 and F["level"](right, 440) < .005
    finally:
        engine.close()


def gain_and_limiter():
    """Test pre-encode sample gain and overload protection without codec overshoot."""
    for gain, sample, expected in ((-6, .2, .2 * 10 ** (-6 / 20)), (6, .9, .95)):
        config = normalize({"master_gain_db": 0}, mixer=True)
        config["sources"][0]["gain_db"] = gain
        engine = MixerEngine(config, F["Audio"](), lambda command: None)
        emitted = []
        engine.encoder = SimpleNamespace(write=emitted.append)
        values = array("f", [sample] * SAMPLES)
        if sys.byteorder != "little":
            values.byteswap()
        engine.captures[(1, "pcm")] = InputCapture(pcm=bytearray(values.tobytes()), first_at=0, position=0)
        engine.mix_frame()
        actual = array("f", emitted[0])
        if sys.byteorder != "little":
            actual.byteswap()
        assert all(abs(v - expected) < 1e-5 for v in actual)
        assert not engine.captures[(1, "pcm")].pcm


def bounds_and_cleanup():
    """Bound admitted streams and encoded queues; global shutdown reaps all children."""
    engine = MixerEngine(normalize({}, mixer=True), F["Audio"](), lambda command: None)
    try:
        for index in range(MAX_STREAMS):
            engine.command(1, {"action": "start", "stream_id": str(index)})
        try:
            engine.command(2, {"action": "start", "stream_id": "overflow"})
        except ValueError:
            pass
        else:
            raise AssertionError("Unbounded capture admission")
    finally:
        engine.close()
    engine = MixerEngine(normalize({}, mixer=True), F["Audio"](), lambda command: None)
    try:
        engine.feed(1, F["frame"](F["encoded"]()))
        F["run_until"](engine, lambda: engine.encoder is not None)
        children = [capture.decoder.process for capture in engine.captures.values()] + [engine.encoder.process]
        try:
            engine.encoder.write(b"x" * (MAX_BUFFER + 1))
        except ValueError:
            pass
        else:
            raise AssertionError("Unbounded encoded queue")
        start = time.monotonic()
        engine.close()
        assert time.monotonic() - start < 1
        assert all(child.poll() is not None for child in children)
    finally:
        engine.close()


if __name__ == "__main__":
    live_and_reuse()
    stereo()
    gain_and_limiter()
    bounds_and_cleanup()
    print("[ok] Live output before Stop, successive cycles, stereo, gain/limiter, bounds and cleanup")
