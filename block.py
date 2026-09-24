"""Autonomous real-time Opus mixing."""
import shutil
from bloxsmith_app.block_api import BlockDefinition, BlockRuntimePreparation, BlockRuntimeResult
from .config import normalize, validate_ports
from .runtime import execute, listen, failure
from .ui import AudioUI
from .engine import MixerEngine


# FB1: Stable paired source ports and validated, explicit lifecycle commands.
# FB2: Independent bounded streams, completion reconciliation and prompt cancellation.
# FB3: Active listening from Run; safe simulation; autonomous managed/linked packaging.
# FB4: Accessible release-scoped translated UI with staged source changes.
class AudioMixerBlock(AudioUI, BlockDefinition):
    """Keep runtime and all properties inside this release, never in the framework."""
    kind = "audio_mixer"
    mixer = True

    def prepare_runtime(self, context):
        """Deterministic validation only: no process, audio or model IO."""
        config = normalize(context.config, mixer=self.mixer)
        validate_ports(context, config)
        return BlockRuntimePreparation(listen_on_run=context.runtime_mode == "zeromq_active")

    def initialize_runtime(self, context):
        """Check local dependencies without starting audio or publishing outputs."""
        if self.mixer and context.runtime_mode == "zeromq_active" and not shutil.which("ffmpeg"):
            return failure("Audio Mixer requires an installed FFmpeg with libopus.")
        return BlockRuntimeResult(last_message="Ready. Audio listening starts with Run.")

    def execute_runtime(self, context):
        """Delegate fresh lifecycle events to the persistent listener."""
        return execute(context, mixer=self.mixer)

    def listen_runtime(self, context):
        """Own continuous audio processing independently of Play and data executions."""
        listen(context, MixerEngine, mixer=self.mixer)
