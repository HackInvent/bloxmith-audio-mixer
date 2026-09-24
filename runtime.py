"""Shared package-local listener contract; no cross-package implementation imports."""
import json
import time
from bloxsmith_app.block_api import BlockRuntimeOutput, BlockRuntimeResult
from .config import commands, normalize, validate_ports


def failure(error):
    """Return a bounded diagnostic without exposing audio payloads."""
    return BlockRuntimeResult(status="failed", error=str(error)[:400], last_message="Audio processing failed.")


def execute(context, *, mixer=False):
    """Transfer fresh message deliveries only; audio never triggers graph executions."""
    try:
        config = normalize(context.config, mixer=mixer)
        validate_ports(context, config)
        if context.runtime_mode != "zeromq_active":
            return BlockRuntimeResult(status="skipped", last_message="Simulation: continuous audio requires Active Runtime.")
        by_port = {row["id"] * 2: row["id"] for row in config["sources"]}
        pending = []
        if context.input_events:
            for event in context.input_events:
                if event.input_port_id in by_port:
                    pending.extend({"source": by_port[event.input_port_id], "command": item} for item in commands(event.value))
        else:
            for port, source in by_port.items():
                attribute = context.input_attribute(f"command_in_{source}")
                if attribute is not None and attribute.status == "updated":
                    pending.extend({"source": source, "command": item} for item in commands(attribute.value))
        if not pending:
            return BlockRuntimeResult(status="skipped", last_message="Listening for audio.")
        if len(pending) > 64:
            raise ValueError("Too many lifecycle commands in one activation.")
        sender = context.services.get("runtime_listener")
        if sender is None:
            raise ValueError("Audio listener unavailable. Stop, then Run.")
        sender.send({"commands": pending})
        return BlockRuntimeResult(last_message="Source lifecycle forwarded.")
    except (ValueError, TypeError) as error:
        return failure(error)


def listen(context, engine_type, *, mixer=False):
    """Fair bounded polling across connected sources; all state is owned by this Run."""
    audio = context.services.get("runtime_audio_streams")
    engine = None
    fatal_error = None
    try:
        config = normalize(context.config, mixer=mixer)
        if audio is None or not audio.available:
            raise ValueError("Connect an audio source and audio_out before Run.")
        connected = {route.port_name for route in audio.port_routes if route.direction == "input"}
        sources = [row for row in config["sources"] if f'audio_in_{row["id"]}' in connected]
        if not sources or not any(route.direction == "output" and route.port_name == "audio_out" for route in audio.port_routes):
            raise ValueError("Connect at least one audio input and audio_out before Run.")

        def emit(command):
            """Use only the public result mailbox for explicit lifecycle outputs."""
            context.emit_result(BlockRuntimeResult(outputs=[BlockRuntimeOutput(
                port_id=2, port_name="command_out", value=json.dumps(command), content_type="application/json")],
                metadata={context.kind: {"state": command["action"], "stream_id": command["stream_id"]}},
                last_message="Audio stream started." if command["action"] == "start" else "Audio stream finished."))

        engine = engine_type(config, audio, emit)
        while not context.stop_requested():
            for _ in range(16):
                received = context.receive_command(timeout_sec=0)
                if received is None:
                    break
                for item in received.payload["commands"]:
                    engine.command(item["source"], item["command"])
            for row in sources:
                for _ in range(8):
                    frame = audio.receive_port(f'audio_in_{row["id"]}', timeout_sec=0)
                    if frame is None:
                        break
                    engine.feed(row["id"], frame)
            engine.step()
            time.sleep(.002)
    except Exception as error:
        fatal_error = error
    finally:
        if engine is not None:
            engine.close()
        # Abort lifecycle messages must not overwrite the final failure state.
        if fatal_error is not None and not context.stop_requested():
            context.emit_result(failure(fatal_error))
