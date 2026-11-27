from base64 import b64encode
import struct

from release.http_api import ReleaseHooks
from samples.demo import sample_wave
from tests.support import HttpCase, report, unpack_audio


class ProgramProofTests(HttpCase):
    def test_freeze_clips(self):
        records, program = self.prepare()
        program_id = program['program_id']
        first, second = program['entries']
        ids = [record['recording_id'] for record in records]
        self.assertNotEqual(*ids)
        self.assertEqual([first['recording_id'], second['recording_id']], ids)
        self.assertEqual([first['priority'], second['priority']], [1, 2])
        self.assertEqual([(row['start_ms'], row['end_ms']) for row in program['entries']], [(100, 300)] * 2)
        actual_spans = [[row['start_frame'], row['end_frame']] for row in program['entries']]
        self.assertEqual(actual_spans, [[800, 2400], [800, 2400]])
        expected_samples = [i % 257 - 128 for i in range(800, 2400)]
        observed = []
        for priority, recording in enumerate(records, 1):
            proof = self.proof_audio(program_id, priority)
            fmt, frames = unpack_audio(proof)
            values = [sample[0] for sample in struct.iter_unpack('<h', frames)]
            self.assertEqual(fmt, (8000, 1, 2))
            self.assertEqual(values, expected_samples)
            self.assertEqual((proof['recording_id'], proof['credit']), (recording['recording_id'], recording['credit']))
            observed.append([len(values), values[0], values[-1], proof['credit']])
        report('v1', {'sample_rate': 8000, 'interval_ms': [100, 300], 'recording_ids': ids},
               [[800, 2400], [800, 2400]], actual_spans,
               [[1600, -99, -42, '陈甲'], [1600, -99, -42, '周乙']], observed,
               ['editorial/excerpts.py', 'staging/clip_bytes.py', 'staging/proof_listening.py'],
               '8 frames per ms; original sample i is i modulo 257 minus 128')

    def test_same_bytes_preserve_origin(self):
        records, program = self.prepare()
        reads = [self.checked(self.editor('GET', f'/recordings/{r["recording_id"]}')) for r in records]
        self.assertEqual(reads[0]['audio_b64'], reads[1]['audio_b64'])
        proofs = [self.proof_audio(program['program_id'], priority) for priority in (1, 2)]
        self.assertEqual(proofs[0]['digest'], proofs[1]['digest'])
        self.assertEqual(proofs[0]['audio_b64'], proofs[1]['audio_b64'])
        self.assertNotEqual(proofs[0]['recording_id'], proofs[1]['recording_id'])
        self.assertEqual([p['actor_id'] for p in proofs], ['jia', 'yi'])
        self.assertEqual([p['credit'] for p in proofs], ['陈甲', '周乙'])

    def test_freeze_snapshot(self):
        records, original = self.prepare()
        p = original['program_id']
        before = self.stage(p)
        rows = [{'recording_id': r['recording_id'], 'start_ms': 25, 'end_ms': 85} for r in reversed(records)]
        edit = self.checked(self.editor('POST', '/drafts', {'draft_id': 1, 'title': '另一份编排', 'candidates': rows}))
        second = self.checked(self.editor('POST', '/programs/freeze', {'draft_id': edit['draft_id']}), 201)
        self.assertNotEqual(second['program_id'], p)
        self.assertEqual(self.checked(self.editor('GET', f'/programs/{p}')), original)
        self.assertEqual(self.stage(p), before)
        self.assertEqual(self.stage(second['program_id'])['entries'][0]['recording_id'], records[1]['recording_id'])

    def test_stage_integrity(self):
        def change_sample(entry, audio):
            if entry.candidate.priority == 1:
                return audio[:-2] + bytes([audio[-2] ^ 1, audio[-1]])
            return audio

        records, program = self.prepare()
        pid = program['program_id']
        old = self.proof_audio(pid, 1)
        self.reopen(ReleaseHooks(before_verification=change_sample))
        failure = self.checked(self.release('POST', '/stages', {'program_id': pid}), 422)
        self.assertEqual(failure, {'error': 'stage_failed', 'priorities': [1]})
        self.assertEqual(self.checked(self.release('GET', f'/proofs/{pid}/1'), 404)['error'], 'proof_unavailable')
        self.assertEqual(self.proof_audio(pid, 2)['recording_id'], records[1]['recording_id'])
        self.checked(self.public(pid), 404)
        self.grant('permit-jia', records[0])
        self.assertEqual(self.checked(self.publish('stage-failure', pid), 422)['error'], 'no_eligible_source')
        self.reopen()
        self.stage(pid)
        self.assertEqual(self.proof_audio(pid, 1), old)
        self.assertEqual(self.checked(self.publish('stage-failure', pid))['recording_id'], records[0]['recording_id'])

    def test_intake_errors(self):
        wav = sample_wave()
        base = {'actor_id': 'jia', 'credit': '陈甲', 'audio_b64': b64encode(wav).decode('ascii')}
        for fields in ({'audio_b64': ''}, {'audio_b64': b64encode(wav[:-1]).decode('ascii')},
                       {'audio_b64': b64encode(sample_wave(44100, 1)[:-2]).decode('ascii')},
                       {'audio_b64': 'not base64!'}, {'actor_id': ''}, {'credit': ' '}):
            with self.subTest(fields=list(fields)):
                self.checked(self.editor('POST', '/recordings', {**base, **fields}), 422)
        self.checked(self.editor('GET', '/recordings/1'), 404)
        self.assertEqual(self.record('jia', '陈甲')['recording_id'], 1)

    def test_out_of_bounds(self):
        recording = self.record('jia', '陈甲')
        row = {'recording_id': recording['recording_id'], 'start_ms': 100, 'end_ms': 401}
        draft = self.draft([row])
        draft_id = draft['draft_id']
        result = self.checked(self.editor('POST', '/programs/freeze', {'draft_id': draft_id}), 422)
        self.assertEqual(result, {'error': 'invalid_excerpt', 'priority': 1})
        self.assertEqual(self.checked(self.editor('GET', f'/drafts/{draft_id}')), draft)
        self.checked(self.editor('GET', '/programs/1'), 404)
        corrected = {'draft_id': draft_id, 'title': draft['title'], 'candidates': [{**row, 'end_ms': 400}]}
        self.checked(self.editor('POST', '/drafts', corrected))
        frozen = self.checked(self.editor('POST', '/programs/freeze', {'draft_id': draft_id}), 201)
        self.assertEqual((frozen['program_id'], frozen['entries'][0]['end_ms']), (1, 400))

    def test_excerpt_boundaries(self):
        recording = self.record('jia', '陈甲')
        base = {'recording_id': recording['recording_id'], 'start_ms': 100, 'end_ms': 300}
        for changes, error in (({'recording_id': 100}, 'unknown_recording'),
                               ({'end_ms': 100}, 'invalid_excerpt'), ({'end_ms': 99}, 'invalid_excerpt'),
                               ({'start_ms': 10.5}, 'invalid_excerpt'), ({'start_ms': True}, 'invalid_excerpt'),
                               ({'start_ms': -1}, 'invalid_excerpt')):
            with self.subTest(changes=changes):
                draft = self.draft([base, {**base, **changes}])
                result = self.checked(self.editor('POST', '/programs/freeze', {'draft_id': draft['draft_id']}), 422)
                self.assertEqual(result, {'error': error, 'priority': 2})
        self.checked(self.editor('GET', '/programs/1'), 404)
        result = self.freeze([recording['recording_id']], 0, 400)
        self.assertEqual(result['entries'][0]['end_frame'], 3200)

    def test_stage_is_private(self):
        records, program = self.prepare()
        pid = program['program_id']
        proof = self.proof_audio(pid, 1)
        self.assertEqual(proof['recording_id'], records[0]['recording_id'])
        self.assertTrue(proof['audio_b64'])
        self.assertEqual(self.checked(self.public(pid), 404), {'error': 'not_public'})
        self.checked(self.release('GET', f'/proofs/{pid}/1', public=True), 403)
        self.assertEqual(self.checked(self.release('POST', '/stages', {'program_id': 101}), 404)['error'],
                         'unknown_program')
