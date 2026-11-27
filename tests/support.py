from base64 import b64decode, b64encode
from contextlib import ExitStack
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

from festival_http import request_json
from samples.demo import DESK_KEY, local_pair, sample_wave


class HttpCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='festival-test-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.reopen()

    def reopen(self, hooks=None):
        self.stack.close()
        self.editorial_url, self.release_url = self.stack.enter_context(local_pair(self.directory, hooks))

    def editor(self, method, path, data=None):
        return request_json(self.editorial_url, method, path, data, desk_key=DESK_KEY)

    def release(self, method, path, data=None, *, public=False):
        return request_json(self.release_url, method, path, data, desk_key=None if public else DESK_KEY)

    def checked(self, response, status=200):
        actual, result = response
        self.assertEqual(actual, status, result)
        return result

    def record(self, actor, credit, wav=None):
        if wav is None:
            wav = sample_wave()
        data = {'actor_id': actor, 'credit': credit, 'audio_b64': b64encode(wav).decode('ascii')}
        return self.checked(self.editor('POST', '/recordings', data), 201)

    def draft(self, rows, title='渡口来信'):
        return self.checked(self.editor('POST', '/drafts', {'title': title, 'candidates': rows}), 201)

    def freeze(self, recording_ids, start=100, end=300, title='渡口来信'):
        rows = [{'recording_id': identity, 'start_ms': start, 'end_ms': end} for identity in recording_ids]
        draft = self.draft(rows, title)
        return self.checked(self.editor('POST', '/programs/freeze', {'draft_id': draft['draft_id']}), 201)

    def stage(self, program_id):
        return self.checked(self.release('POST', '/stages', {'program_id': program_id}))

    def prepare(self, actors=(('jia', '陈甲'), ('yi', '周乙')), *, wav=None, start=100, end=300):
        wav = sample_wave() if wav is None else wav
        records = [self.record(actor, credit, wav) for actor, credit in actors]
        program = self.freeze([record['recording_id'] for record in records], start, end)
        self.stage(program['program_id'])
        return records, program

    @staticmethod
    def action(action_id, record, grant_id=None):
        body = {'action_id': action_id, 'actor_id': record['actor_id'], 'recording_id': record['recording_id'],
                'purpose': 'preview_release', 'kind': 'grant' if grant_id is None else 'withdraw'}
        if grant_id is not None:
            body['grant_id'] = grant_id
        return body

    def grant(self, action_id, record):
        return self.checked(self.editor('POST', '/consent', self.action(action_id, record)))

    def withdraw(self, action_id, record, grant_id):
        return self.checked(self.editor('POST', '/consent', self.action(action_id, record, grant_id)))

    def publish(self, request_id, program_id):
        return self.release('POST', '/releases', {'request_id': request_id, 'program_id': program_id})

    def public(self, program_id):
        return self.release('GET', f'/listen/preview-{program_id}', public=True)

    def proof_audio(self, program_id, priority):
        return self.checked(self.release('GET', f'/proofs/{program_id}/{priority}'))


def unpack_audio(body):
    with wave.open(BytesIO(b64decode(body['audio_b64'], validate=True)), 'rb') as pcm:
        return (pcm.getframerate(), pcm.getnchannels(), pcm.getsampwidth()), pcm.readframes(pcm.getnframes())


def report(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    body = {'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
            'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
            'code_paths': code_paths, 'oracle': oracle}
    print('POINTWISE_SCENARIO ' + json.dumps(body, ensure_ascii=False, sort_keys=True))
