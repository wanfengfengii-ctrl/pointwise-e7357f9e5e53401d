from dataclasses import dataclass
from io import BytesIO
import struct
import wave


@dataclass(frozen=True)
class PcmWave:
    sample_rate: int
    channels: int
    sample_width: int
    frames: bytes

    @property
    def frame_size(self):
        return self.channels * self.sample_width

    @property
    def frame_count(self):
        return len(self.frames) // self.frame_size


def _riff_data_size(raw):
    if len(raw) < 12 or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
        raise ValueError('expected a RIFF WAVE file')
    if struct.unpack_from('<I', raw, 4)[0] + 8 != len(raw):
        raise ValueError('RIFF length does not match input')
    offset = 12
    fmt = None
    data_size = None
    while offset < len(raw):
        if len(raw) - offset < 8:
            raise ValueError('incomplete chunk header')
        tag, size = struct.unpack_from('<4sI', raw, offset)
        start = offset + 8
        offset = start + size + (size & 1)
        if offset > len(raw):
            raise ValueError('incomplete chunk')
        if tag == b'fmt ':
            if fmt is not None or size < 16:
                raise ValueError('invalid format chunk')
            fmt = struct.unpack_from('<HHIIHH', raw, start)
        elif tag == b'data':
            if fmt is None or data_size is not None:
                raise ValueError('invalid data chunk order')
            data_size = size
    if fmt is None or data_size is None:
        raise ValueError('missing WAV format or audio')
    encoding, channels, rate, byte_rate, alignment, bits = fmt
    if encoding != 1 or channels not in (1, 2) or rate <= 0 or bits != 16:
        raise ValueError('expected 16-bit mono or stereo PCM')
    if alignment != channels * 2 or byte_rate != rate * alignment:
        raise ValueError('inconsistent PCM format')
    if not data_size or data_size % alignment:
        raise ValueError('empty or incomplete PCM frames')
    return data_size


def read_pcm_wave(raw):
    size = _riff_data_size(raw)
    try:
        with wave.open(BytesIO(raw), 'rb') as source:
            frames = source.readframes(source.getnframes())
            pcm = PcmWave(source.getframerate(), source.getnchannels(), source.getsampwidth(), frames)
    except (EOFError, wave.Error) as error:
        raise ValueError('unreadable WAV') from error
    if len(pcm.frames) != size:
        raise ValueError('truncated PCM frames')
    return pcm


def write_pcm_wave(pcm):
    if (pcm.channels not in (1, 2) or pcm.sample_width != 2 or pcm.sample_rate <= 0
            or not pcm.frames or len(pcm.frames) % pcm.frame_size):
        raise ValueError('invalid PCM frames or format')
    output = BytesIO()
    with wave.open(output, 'wb') as target:
        target.setnchannels(pcm.channels)
        target.setsampwidth(pcm.sample_width)
        target.setframerate(pcm.sample_rate)
        target.writeframes(pcm.frames)
    return output.getvalue()
