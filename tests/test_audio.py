from base64 import b64encode
from io import BytesIO
import struct
import wave

from samples.demo import sample_wave
from tests.support import HttpCase, report, unpack_audio


class AudioTests(HttpCase):
    def test_frame_alignment_stereo(self):
        wav = sample_wave(rate=44100, channels=2)
        records, program = self.prepare((('jia', '陈甲'),), wav=wav, start=101, end=102)
        self.assertEqual(records[0]['duration_ms'], 400)
        entry = program['entries'][0]
        actual_span = [entry['start_frame'], entry['end_frame']]
        self.assertEqual(actual_span, [4455, 4499])
        fmt, raw = unpack_audio(self.proof_audio(program['program_id'], 1))
        frames = list(struct.iter_unpack('<hh', raw))
        expected = [(i % 257 - 128, 128 - i % 257) for i in range(4455, 4499)]
        self.assertEqual(fmt, (44100, 2, 2))
        self.assertEqual(frames, expected)
        actual = [len(frames), list(frames[0]), list(frames[-1])]
        self.assertEqual(actual, [44, [-42, 42], [1, -1]])
        report('v1.frame_alignment', {'sample_rate': 44100, 'channels': 2, 'interval_ms': [101, 102]},
               [4455, 4499], actual_span, [44, [-42, 42], [1, -1]], actual,
               ['catalog/wave_source.py', 'editorial/excerpts.py', 'staging/verification.py'],
               '101 ms is frame time 4454.1; 102 ms is 4498.2. Include frame starts 4455 through 4498.')

    def test_unusable_and_partial_pcm_has_no_recording(self):
        clips = []
        for count, width in ((44, 2), (80, 1)):
            buffer = BytesIO()
            with wave.open(buffer, 'wb') as wav:
                wav.setparams((1, width, 44100, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes(count * width))
            clips.append(buffer.getvalue())
        raw = bytearray(sample_wave())
        data_size = struct.unpack_from('<I', raw, 40)[0]
        struct.pack_into('<I', raw, 40, data_size - 1)
        clips.append(bytes(raw))
        for clip in clips:
            self.checked(self.editor('POST', '/recordings', {
                'actor_id': 'jia', 'credit': '陈甲', 'audio_b64': b64encode(clip).decode('ascii')
            }), 422)
        self.checked(self.editor('GET', '/recordings/1'), 404)
