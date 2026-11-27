from dataclasses import dataclass
from hashlib import sha256

from catalog.wave_source import PcmWave, read_pcm_wave


@dataclass(frozen=True)
class VerifiedClip:
    audio: bytes
    digest: str


def verify_clip(audio, expected: PcmWave):
    actual = read_pcm_wave(audio)
    if actual != expected:
        raise ValueError('staged WAV differs from source format or frames')
    return VerifiedClip(audio, sha256(audio).hexdigest())
