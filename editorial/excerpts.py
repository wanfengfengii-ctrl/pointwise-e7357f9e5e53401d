from dataclasses import dataclass

from catalog.audio_metadata import AudioMetadata


@dataclass(frozen=True)
class Excerpt:
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class FrameSpan:
    start_frame: int
    end_frame: int


def validate_excerpt(start_ms, end_ms, metadata: AudioMetadata):
    if type(start_ms) is not int or type(end_ms) is not int:
        raise ValueError('excerpt endpoints must be integer milliseconds')
    if not 0 <= start_ms < end_ms <= metadata.duration_ms:
        raise ValueError('excerpt outside the original recording')
    return Excerpt(start_ms, end_ms)


def project_frames(excerpt: Excerpt, metadata: AudioMetadata):
    start = (excerpt.start_ms * metadata.sample_rate + 999) // 1000
    end = (excerpt.end_ms * metadata.sample_rate + 999) // 1000
    if not 0 <= start < end <= metadata.frame_count:
        raise ValueError('excerpt has no complete frame span')
    return FrameSpan(start, end)
