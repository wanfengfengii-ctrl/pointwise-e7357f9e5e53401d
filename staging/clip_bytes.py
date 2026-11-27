from catalog.wave_source import PcmWave, read_pcm_wave, write_pcm_wave
from editorial.excerpts import FrameSpan


def extract_source_frames(original, span: FrameSpan):
    pcm = read_pcm_wave(original)
    if not 0 <= span.start_frame < span.end_frame <= pcm.frame_count:
        raise ValueError('frozen span is outside source PCM')
    start = span.start_frame * pcm.frame_size
    end = span.end_frame * pcm.frame_size
    return PcmWave(pcm.sample_rate, pcm.channels, pcm.sample_width, pcm.frames[start:end])


def render_clip(source_frames: PcmWave):
    return write_pcm_wave(source_frames)
