"""Bounded source configuration and stable audio/command port identities."""
from collections.abc import Mapping
import json
import math

MAX_SOURCES = 8
MAX_STREAMS = 16
MAX_BUFFER = 2 * 1024 * 1024
DEFAULT_SOURCES = [{"id": 1, "label": "Source 1", "gain_db": 0, "muted": False},
                   {"id": 2, "label": "Source 2", "gain_db": 0, "muted": False}]


def number(value, low, high, name, *, integer=False):
    """Reject booleans, non-finite values and out-of-range authored settings."""
    if isinstance(value, bool):
        raise ValueError(f"{name}: expected a number.")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name}: expected a number.") from None
    if not math.isfinite(result) or not low <= result <= high or (integer and result != int(result)):
        raise ValueError(f"{name}: expected {'an integer' if integer else 'a number'} between {low} and {high}.")
    return int(result) if integer else result


def normalize(raw, *, mixer=False):
    """Accept immutable runtime snapshots; preserve no mutable shared defaults."""
    raw = raw or {}
    rows = raw.get("sources", DEFAULT_SOURCES)
    if not isinstance(rows, (list, tuple)) or not 2 <= len(rows) <= MAX_SOURCES:
        raise ValueError("Configure between 2 and 8 sources.")
    sources, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Each source must be an object.")
        key = number(row.get("id"), 1, 999999, "Source id", integer=True)
        label = str(row.get("label", "")).strip()
        if key in seen or not label or len(label) > 14:
            raise ValueError("Source IDs must be unique; labels must contain 1–14 characters.")
        seen.add(key)
        muted = row.get("muted", False)
        if not isinstance(muted, bool):
            raise ValueError("Mute must be a boolean.")
        sources.append({"id": key, "label": label,
                        "gain_db": number(row.get("gain_db", 0), -60, 6, "Source gain"), "muted": muted})
    if not {1, 2} <= seen:
        raise ValueError("The two default sources must remain present.")
    config = {"sources": sources, "drain_timeout_sec": number(raw.get("drain_timeout_sec", 5), 1, 20, "Drain timeout")}
    if mixer:
        config.update(buffer_ms=number(raw.get("buffer_ms", 150), 40, 1000, "Buffer", integer=True),
                      master_gain_db=number(raw.get("master_gain_db", -6), -60, 6, "Output gain"),
                      channels=number(raw.get("channels", 1), 1, 2, "Output channels", integer=True))
    return config


def source_ports(source):
    """Keep machine names/IDs stable when labels or visual order change."""
    key, label = source["id"], source["label"]
    base = {"multiplicity": "one", "required": False, "execution_requirement": "not_required_for_execution"}
    return [
        {**base, "id": key * 2 - 1, "name": f"audio_in_{key}", "title": f"{label} audio",
         "accepts": ["audio/*"], "transport": "audio_stream",
         "audio_stream": {"codecs": ["opus"], "sample_rates_hz": [48000], "channels": [1, 2], "overflow_policy": "disconnect"}},
        {**base, "id": key * 2, "name": f"command_in_{key}", "title": f"{label} cmd",
         "accepts": ["application/json"], "transport": "message"},
    ]


def validate_ports(context, config):
    """Validate immutable identity, not serialized port order."""
    expected = [port for row in config["sources"] for port in source_ports(row)]
    actual = {p.id: p for p in context.input_ports}
    if len(actual) != len(context.input_ports) or set(actual) != {p["id"] for p in expected}:
        raise ValueError("Source pairs and input ports differ. Apply the source settings before Run.")
    for port in expected:
        item = actual[port["id"]]
        if (item.name != port["name"] or getattr(item, "transport", "message") != port["transport"]
                or item.required or item.multiplicity != "one"
                or getattr(item, "execution_requirement", "not_required_for_execution") != "not_required_for_execution"):
            raise ValueError("Source audio/command port identities must remain unchanged.")
    outputs = {p.id: p for p in context.output_ports}
    if len(context.output_ports) != 2 or set(outputs) != {1, 2} or any(
        outputs[key].name != name or getattr(outputs[key], "transport", "message") != transport
        for key, name, transport in ((1, "audio_out", "audio_stream"), (2, "command_out", "message"))):
        raise ValueError("The audio_out and command_out outputs must remain unchanged.")


def commands(raw):
    """Validate a lifecycle batch atomically, including producer completion totals."""
    if isinstance(raw, str):
        if len(raw) > 65536:
            raise ValueError("Lifecycle message is too large.")
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError("Expected start/stop JSON.") from None
    values = raw if isinstance(raw, list) else [raw]
    if not 1 <= len(values) <= 64:
        raise ValueError("Expected 1–64 lifecycle commands.")
    result = []
    for item in values:
        if not isinstance(item, Mapping) or item.get("action") not in {"start", "stop"}:
            raise ValueError("Only source start/stop commands are supported.")
        stream = item.get("stream_id")
        if not isinstance(stream, str) or not 1 <= len(stream) <= 128 or not stream.strip():
            raise ValueError("A non-empty stream_id is required.")
        allowed = {"action", "stream_id"}
        output = {"action": item["action"], "stream_id": stream}
        if item["action"] == "stop":
            allowed |= {"frame_count", "byte_count", "aborted"}
            for key in ("frame_count", "byte_count"):
                if type(item.get(key)) is not int or not 0 <= item[key] <= 2**53 - 1:
                    raise ValueError(f"Stop requires a non-negative integer {key}.")
                output[key] = item[key]
            if not isinstance(item.get("aborted", False), bool):
                raise ValueError("aborted must be a boolean.")
            output["aborted"] = item.get("aborted", False)
        if set(item) - allowed:
            raise ValueError("Unknown lifecycle fields; connect the producer command_out, not VAD events.")
        result.append(output)
    return result
