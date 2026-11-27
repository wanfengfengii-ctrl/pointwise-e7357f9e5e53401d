from dataclasses import dataclass

from catalog.wave_source import PcmWave


@dataclass(frozen=True)
class AudioMetadata:
    sample_rate: int
    channels: int
    sample_width: int
    frame_count: int
    duration_ms: int


def measure_audio(pcm: PcmWave):
    duration = 1000 * pcm.frame_count // pcm.sample_rate
    if not duration:
        raise ValueError('no complete millisecond of audio')
    return AudioMetadata(pcm.sample_rate, pcm.channels, pcm.sample_width, pcm.frame_count, duration)
