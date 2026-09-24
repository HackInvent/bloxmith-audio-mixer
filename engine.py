"""Bounded live Opus decoding, clocked PCM mixing and Ogg/Opus encoding.

All processes belong to the listener. No network, device, detached thread or
framework internal is used. Input containers are always decoded independently.
"""
from array import array
from collections import deque
from dataclasses import dataclass, field
import math
import os
import subprocess
import sys
import time
import uuid
from .config import MAX_BUFFER, MAX_STREAMS

RATE = 48000
SAMPLES = 960
PERIOD = SAMPLES / RATE


class Pipe:
    """Non-blocking, bounded FFmpeg pipes with deterministic child cleanup."""

    def __init__(self, args):
        self.process = subprocess.Popen(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1", *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.pending = bytearray()
        self.errors = bytearray()
        self.ending = self.eof = False
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            os.set_blocking(pipe.fileno(), False)

    def write(self, data):
        """Queue bounded bytes; never block the runtime listener on an OS pipe."""
        if self.ending or len(self.pending) + len(data) > MAX_BUFFER:
            raise ValueError("FFmpeg input buffer exceeded its limit or is already closed.")
        self.pending.extend(data)

    def finish(self):
        """Close stdin only after every queued byte has reached the codec."""
        self.ending = True

    def pump(self):
        """Advance both pipe directions fairly and return bounded output chunks."""
        if self.pending:
            try:
                written = os.write(self.process.stdin.fileno(), self.pending[:65536])
                del self.pending[:written]
            except BlockingIOError:
                pass
            except BrokenPipeError:
                raise ValueError("FFmpeg stopped accepting audio.") from None
        if self.ending and not self.pending and not self.process.stdin.closed:
            self.process.stdin.close()
        output = []
        for _ in range(16):
            try:
                data = os.read(self.process.stdout.fileno(), 8192)
            except BlockingIOError:
                break
            if not data:
                self.eof = True
                break
            output.append(data)
        try:
            data = os.read(self.process.stderr.fileno(), 4096)
            self.errors.extend(data)
            del self.errors[:-4096]
        except BlockingIOError:
            pass
        code = self.process.poll()
        if code is not None and code != 0:
            raise ValueError("FFmpeg could not process this Opus stream.")
        return output

    @property
    def done(self):
        """EOF must be observed as well as a successful process exit."""
        return self.eof and self.process.poll() == 0

    def close(self):
        """Kill only our codec process, then reap it with a short finite deadline."""
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=.05)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            pipe.close()


@dataclass
class InputCapture:
    """One independently decoded source clock and its completion reconciliation."""
    frames: int = 0
    size: int = 0
    profile: tuple | None = None
    prefix: bytearray = field(default_factory=bytearray)
    pcm: bytearray = field(default_factory=bytearray)
    decoder: Pipe | None = None
    stop: dict | None = None
    deadline: float = 0
    first_at: float | None = None
    position: int | None = None
    ended: bool = False


class MixerEngine:
    """Mix on a 20 ms clock; finish only after every participating source drains."""

    def __init__(self, config, audio, emit):
        self.config, self.audio, self.emit = config, audio, emit
        self.sources = {row["id"]: row for row in config["sources"]}
        self.captures, self.retired = {}, deque(maxlen=256)
        self.encoder = None
        self.stream_id = None
        self.frames = self.size = self.cursor = 0
        self.origin = self.due = 0
        self.finishing = False
        self.finish_deadline = 0
        self.limiter = 1.0
        self.sample_bytes = config["channels"] * 4

    def capture(self, key):
        """Admit a bounded stream set; two equal IDs on different ports stay separate."""
        if key in self.retired:
            return None
        if key not in self.captures:
            if len(self.captures) >= MAX_STREAMS:
                raise ValueError("Too many open mixer streams; connect producer commands.")
            self.captures[key] = InputCapture()
        return self.captures[key]

    def command(self, source, command):
        """A producer abort removes only that capture, never the other mixer sources."""
        key = source, command["stream_id"]
        item = self.capture(key)
        if item is None or command["action"] == "start":
            return
        if item.stop is not None and item.stop != command:
            raise ValueError("Conflicting mixer source completion totals.")
        item.stop = command
        item.deadline = time.monotonic() + self.config["drain_timeout_sec"]
        if item.frames > command["frame_count"] or item.size > command["byte_count"]:
            raise ValueError("Stop totals are smaller than the received source.")
        if command["aborted"]:
            self.retire(key)
        else:
            self.finish_input(item)

    def feed(self, source, frame):
        """Decode WebM/Ogg separately and preserve first samples despite codec startup."""
        key = source, frame.stream_id
        item = self.capture(key)
        if item is None:
            return
        if frame.sequence != item.frames + 1:
            raise ValueError("Missing, duplicated or reordered source audio frame.")
        profile = frame.codec, frame.sample_rate_hz, frame.channels
        if profile[:2] != ("opus", RATE) or profile[2] not in (1, 2) or (item.profile and item.profile != profile):
            raise ValueError("Expected a stable 48 kHz mono/stereo Opus stream.")
        if item.stop and (item.frames + 1 > item.stop["frame_count"] or item.size + len(frame.payload) > item.stop["byte_count"]):
            raise ValueError("Audio exceeds source stop totals.")
        item.profile = profile
        item.frames += 1
        item.size += len(frame.payload)
        if item.first_at is None:
            item.first_at = time.monotonic()
        if item.decoder is None:
            if len(item.prefix) + len(frame.payload) > MAX_BUFFER:
                raise ValueError("Container prefix exceeded the buffer limit.")
            item.prefix.extend(frame.payload)
            if len(item.prefix) >= 4:
                container = "ogg" if item.prefix[:4] == b"OggS" else "webm" if item.prefix[:4] == b"\x1aE\xdf\xa3" else None
                if container is None:
                    raise ValueError("Audio Mixer accepts Opus in WebM or Ogg only.")
                item.decoder = Pipe(["-probesize", "32", "-analyzeduration", "0", "-f", container, "-i", "pipe:0",
                    "-map", "0:a:0", "-vn", "-ac", str(self.config["channels"]), "-ar", str(RATE),
                    "-c:a", "pcm_f32le", "-f", "f32le", "-flush_packets", "1", "pipe:1"])
                item.decoder.write(item.prefix)
                item.prefix.clear()
        else:
            item.decoder.write(frame.payload)
        self.finish_input(item)

    def finish_input(self, item):
        """Signal decoder EOF only when the explicit frame and byte totals match."""
        if item.stop and (item.frames, item.size) == (item.stop["frame_count"], item.stop["byte_count"]):
            if item.decoder:
                item.decoder.finish()
            elif item.size:
                raise ValueError("Incomplete Opus container header.")
            else:
                item.ended = True

    def retire(self, key):
        """Release one decoder and fence late frames/commands for that capture."""
        item = self.captures.pop(key)
        if item.decoder:
            item.decoder.close()
        self.retired.append(key)

    def start_output(self, now):
        """Open a fresh independent Ogg stream, paced from its first decoded audio."""
        self.encoder = Pipe(["-probesize", "32", "-analyzeduration", "0", "-f", "f32le", "-ar", str(RATE), "-ac", str(self.config["channels"]), "-i", "pipe:0",
            "-c:a", "libopus", "-application", "voip", "-frame_duration", "20", "-b:a", "64000",
            "-page_duration", "20000", "-f", "ogg", "-flush_packets", "1", "pipe:1"])
        self.stream_id = uuid.uuid4().hex
        self.origin = min(item.first_at for item in self.captures.values() if item.first_at is not None)
        self.cursor = self.frames = self.size = 0
        self.limiter = 1.0
        self.due = now + self.config["buffer_ms"] / 1000
        self.finishing = False
        self.emit({"action": "start", "stream_id": self.stream_id})

    def mix_frame(self):
        """Sum finite PCM with per-source gain/mute and a peak-safe release limiter."""
        channels = self.config["channels"]
        mixed = [0.0] * (SAMPLES * channels)
        for key, item in list(self.captures.items()):
            if item.position is None:
                if not item.pcm:
                    continue
                item.position = max(self.cursor, round((item.first_at - self.origin) * RATE))
            # Late decoded samples are retained, not silently dropped as a truncated first word.
            item.position = max(self.cursor, item.position)
            offset = item.position - self.cursor
            if offset >= SAMPLES:
                continue
            count = min(SAMPLES - offset, len(item.pcm) // self.sample_bytes)
            values = array("f")
            values.frombytes(bytes(item.pcm[:count * self.sample_bytes]))
            del item.pcm[:count * self.sample_bytes]
            if sys.byteorder != "little":
                values.byteswap()
            row = self.sources[key[0]]
            gain = 0.0 if row["muted"] else 10 ** (row["gain_db"] / 20)
            for index, value in enumerate(values):
                if not math.isfinite(value):
                    raise ValueError("Decoder produced non-finite PCM samples.")
                mixed[offset * channels + index] += value * gain
            item.position += count
        master = 10 ** (self.config["master_gain_db"] / 20)
        peak = max(abs(value * master) for value in mixed)
        target = min(1.0, .95 / peak) if peak else 1.0
        self.limiter = min(target, self.limiter + .1)
        output = array("f", (value * master * self.limiter for value in mixed))
        if sys.byteorder != "little":
            output.byteswap()
        self.encoder.write(output.tobytes())
        self.cursor += SAMPLES

    def step(self):
        """Progress codecs, bounded jitter buffers, pacing, and complete tail drainage."""
        now = time.monotonic()
        for key, item in list(self.captures.items()):
            if item.decoder and not item.ended:
                for chunk in item.decoder.pump():
                    item.pcm.extend(chunk)
                if len(item.pcm) > RATE * self.sample_bytes * 2:
                    raise ValueError("Source exceeded the two-second decoded audio buffer.")
                if item.decoder.done:
                    if not item.stop or (item.frames, item.size) != (item.stop["frame_count"], item.stop["byte_count"]):
                        raise ValueError("Decoder ended without reconciled producer totals.")
                    if len(item.pcm) % self.sample_bytes:
                        raise ValueError("Incomplete decoded PCM sample.")
                    item.ended = True
            if item.stop and not item.ended and now > item.deadline:
                raise ValueError("Timed out draining a source; no successful stop was fabricated.")
            if item.ended and not item.pcm:
                self.retire(key)
        if self.encoder is None and any(item.pcm for item in self.captures.values()):
            self.start_output(now)
        if self.encoder is None:
            return
        if not self.finishing:
            if not self.captures:
                self.finishing = True
                self.finish_deadline = now + self.config["drain_timeout_sec"]
                self.encoder.finish()
            else:
                ticks = 0
                while now >= self.due and ticks < 4:
                    self.mix_frame()
                    self.due += PERIOD
                    ticks += 1
                if now - self.due > .5:
                    raise ValueError("Mixer cannot keep up with real time; reduce the number of sources.")
        for chunk in self.encoder.pump():
            self.frames += 1
            self.size += len(chunk)
            self.audio.publish_port("audio_out", chunk, codec="opus", sample_rate_hz=RATE,
                channels=self.config["channels"], stream_id=self.stream_id, sequence=self.frames,
                timestamp_ms=max(1, round(self.cursor * 1000 / RATE)))
        if self.encoder.done:
            if not self.finishing:
                raise ValueError("Opus encoder stopped before the mix was complete.")
            self.emit({"action": "stop", "stream_id": self.stream_id, "frame_count": self.frames,
                       "byte_count": self.size, "aborted": False})
            self.encoder.close()
            self.encoder = None
            self.stream_id = None
            for item in self.captures.values():
                item.position = None
        elif self.finishing and now > self.finish_deadline:
            raise ValueError("Timed out finishing the mixed Ogg stream.")

    def close(self):
        """Abort unfinished output and promptly reap all block-owned codec processes."""
        for key in list(self.captures):
            self.retire(key)
        if self.encoder:
            self.encoder.close()
            try:
                self.emit({"action": "stop", "stream_id": self.stream_id, "frame_count": self.frames,
                           "byte_count": self.size, "aborted": True})
            except Exception:
                pass
            self.encoder = None
