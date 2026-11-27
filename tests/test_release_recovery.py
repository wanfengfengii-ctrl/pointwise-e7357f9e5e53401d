from http.client import RemoteDisconnected

from festival_http import DropResponse
from release.http_api import ReleaseHooks
from release.receipts import receipt_payload
from tests.support import HttpCase


class ReleaseRecoveryTests(HttpCase):
    def test_lost_reply_and_withdrawal(self):
        commits = []

        def lose(receipt):
            commits.append(receipt_payload(receipt))
            return True

        hooks = ReleaseHooks(drop_after_commit=lose)
        self.reopen(hooks)
        (jia, yi), program = self.prepare()
        pid = program['program_id']
        self.grant('grant-jia', jia)
        self.grant('grant-yi', yi)
        proof = self.proof_audio(pid, 1)
        with self.assertRaises(RemoteDisconnected):
            self.publish('original-number', pid)
        self.assertEqual(len(commits), 1)
        first = commits[0]
        self.assertEqual((first['recording_id'], first['grant_id'], first['credit']),
                         (jia['recording_id'], 'grant-jia', '陈甲'))
        heard = self.checked(self.public(pid))
        self.assertEqual(heard, {**first, 'audio_b64': proof['audio_b64']})
        self.assertEqual(self.withdraw('withdraw-jia', jia, 'grant-jia')['status'], 'applied')
        self.reopen(hooks)
        self.assertEqual(self.checked(self.release('GET', '/releases/original-number')), first)
        self.assertEqual(self.checked(self.publish('original-number', pid)), first)
        self.assertEqual(self.checked(self.public(pid)), heard)
        self.assertEqual(commits, [first])
        other = self.freeze([jia['recording_id'], yi['recording_id']])['program_id']
        self.assertEqual(self.checked(self.publish('original-number', other), 409)['error'], 'request_conflict')
        self.assertEqual(self.checked(self.public(pid)), heard)

    def test_uncommitted_retry(self):
        registrations = []
        commits = []

        def disconnect(request_id):
            registrations.append(request_id)
            raise DropResponse()

        self.reopen(ReleaseHooks(after_registration=disconnect))
        (jia, yi), program = self.prepare()
        pid = program['program_id']
        self.grant('grant-jia', jia)
        self.grant('grant-yi', yi)
        with self.assertRaises(RemoteDisconnected):
            self.publish('uncommitted', pid)
        self.assertEqual(registrations, ['uncommitted'])
        self.checked(self.public(pid), 404)

        def record(receipt):
            commits.append(receipt.request_id)
            return False

        self.reopen(ReleaseHooks(drop_after_commit=record))
        status = self.checked(self.release('GET', '/releases/uncommitted'))
        self.assertEqual(status, {'request_id': 'uncommitted', 'program_id': pid, 'status': 'pending'})
        self.checked(self.public(pid), 404)
        self.withdraw('withdraw-jia', jia, 'grant-jia')
        receipt = self.checked(self.publish('uncommitted', pid))
        self.assertEqual((receipt['recording_id'], receipt['credit']), (yi['recording_id'], '周乙'))
        self.assertEqual(self.checked(self.publish('uncommitted', pid)), receipt)
        self.assertEqual(commits, ['uncommitted'])

    def test_retry_no_source(self):
        (jia,), program = self.prepare((('jia', '陈甲'),))
        pid = program['program_id']
        self.checked(self.release('GET', '/releases/later'), 404)
        self.assertEqual(self.checked(self.publish('later', pid), 422)['error'], 'no_eligible_source')
        self.checked(self.public(pid), 404)
        self.reopen()
        self.assertEqual(self.checked(self.release('GET', '/releases/later'))['status'], 'no_eligible_source')
        self.grant('later-grant', jia)
        receipt = self.checked(self.publish('later', pid))
        self.assertEqual(receipt['grant_id'], 'later-grant')
        self.assertEqual(self.checked(self.release('GET', '/releases/later')), receipt)
        self.assertEqual(self.checked(self.public(pid))['credit'], '陈甲')

    def test_conflicting_request(self):
        (jia, yi), program = self.prepare()
        pid = program['program_id']
        self.grant('grant-jia', jia)
        receipt = self.checked(self.publish('conflicting', pid))
        fixed = self.checked(self.public(pid))
        other = self.freeze([yi['recording_id']], 0, 50)['program_id']
        self.assertEqual(self.checked(self.publish('conflicting', other), 409)['error'], 'request_conflict')
        self.assertEqual(self.checked(self.release('GET', '/releases/conflicting')), receipt)
        self.assertEqual(self.checked(self.public(pid)), fixed)
        self.checked(self.public(other), 404)

    def test_same_sources_are_different_parameters(self):
        (jia, yi), original = self.prepare()
        second = self.freeze([jia['recording_id'], yi['recording_id']])
        self.assertEqual(second['entries'], original['entries'])
        self.assertNotEqual(second['program_id'], original['program_id'])
        self.stage(second['program_id'])
        self.grant('grant-jia', jia)
        receipt = self.checked(self.publish('fixed-identity', original['program_id']))
        self.assertEqual(self.checked(self.publish('fixed-identity', second['program_id']), 409)['error'],
                         'request_conflict')
        self.assertEqual(self.checked(self.release('GET', '/releases/fixed-identity')), receipt)
        self.assertEqual(self.checked(self.public(original['program_id']))['program_id'], original['program_id'])
        self.checked(self.public(second['program_id']), 404)
