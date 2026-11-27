from concurrent.futures import ThreadPoolExecutor
from threading import Event

from release.http_api import ReleaseHooks
from tests.support import HttpCase, report, unpack_audio


class PublicationTests(HttpCase):
    def assert_source(self, receipt, heard, record, grant_id):
        for name in ('recording_id', 'actor_id', 'credit'):
            self.assertEqual(receipt[name], record[name])
            self.assertEqual(heard[name], record[name])
        self.assertEqual(receipt['grant_id'], grant_id)
        self.assertEqual({key: value for key, value in heard.items() if key != 'audio_b64'}, receipt)

    def test_single_source(self):
        (jia,), program = self.prepare((('jia', '陈甲'),))
        pid = program['program_id']
        self.grant('grant-jia', jia)
        receipt = self.checked(self.publish('single-source', pid))
        heard = self.checked(self.public(pid))
        self.assert_source(receipt, heard, jia, 'grant-jia')
        self.assertEqual(unpack_audio(heard), unpack_audio(self.proof_audio(pid, 1)))
        self.assertEqual(self.checked(self.release('GET', '/releases/single-source')), receipt)
        self.assertEqual(self.checked(self.publish('other-number', pid), 409)['error'], 'program_already_published')

    def test_grant_mismatch(self):
        (one, two), _ = self.prepare((('actor', '第一份'), ('actor', '第二份')))
        self.grant('grant-one', one)
        self.grant('grant-two', two)
        mismatched = self.action('bad-withdraw', one, 'grant-two')
        result = self.checked(self.editor('POST', '/consent', mismatched), 422)
        self.assertEqual(result['error'], 'grant_scope_mismatch')
        self.checked(self.editor('GET', '/consent/bad-withdraw'), 404)
        foreign = self.action('wrong-owner', {**one, 'actor_id': 'other'})
        self.assertEqual(self.checked(self.editor('POST', '/consent', foreign), 422)['error'], 'recording_owner_mismatch')
        for index, record, grant_id in ((1, one, 'grant-one'), (2, two, 'grant-two')):
            program = self.freeze([record['recording_id']])
            pid = program['program_id']
            self.stage(pid)
            receipt = self.checked(self.publish(f'scope-{index}', pid))
            self.assert_source(receipt, self.checked(self.public(pid)), record, grant_id)

    def test_pending_consent(self):
        entered, proceed = Event(), Event()

        def delay(action):
            if action.action_id == 'pending-withdraw':
                entered.set()
                if not proceed.wait(6):
                    raise RuntimeError('withdrawal test gate timed out')

        self.reopen(ReleaseHooks(before_apply=delay))
        (jia, yi), program = self.prepare()
        pid = program['program_id']
        self.grant('grant-jia', jia)
        self.grant('grant-yi', yi)
        withdrawal = self.action('pending-withdraw', jia, 'grant-jia')
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(self.editor, 'POST', '/consent', withdrawal)
            try:
                self.assertTrue(entered.wait(4))
                pending = self.checked(self.editor('GET', '/consent/pending-withdraw'), 202)
                self.assertEqual(pending, {**withdrawal, 'status': 'pending'})
                receipt = self.checked(self.publish('while-pending', pid))
                self.assert_source(receipt, self.checked(self.public(pid)), jia, 'grant-jia')
            finally:
                proceed.set()
            confirmed = self.checked(request.result(timeout=6))
        self.assertEqual(confirmed, {**withdrawal, 'status': 'applied'})
        self.assertEqual(self.checked(self.editor('GET', '/consent/pending-withdraw')), confirmed)
        self.assertEqual(self.checked(self.editor('POST', '/consent', withdrawal)), confirmed)
        self.assertEqual(self.checked(self.public(pid))['recording_id'], jia['recording_id'])

    def test_priority_and_latest_grant(self):
        (jia, yi), program = self.prepare()
        self.grant('early-jia', jia)
        self.grant('later-jia', jia)
        self.grant('newest-yi', yi)
        pid = program['program_id']
        receipt = self.checked(self.publish('priority', pid))
        self.assertEqual(receipt['priority'], 1)
        self.assert_source(receipt, self.checked(self.public(pid)), jia, 'later-jia')
        self.withdraw('withdraw-later', jia, 'later-jia')
        other = self.freeze([jia['recording_id'], yi['recording_id']])['program_id']
        self.stage(other)
        receipt = self.checked(self.publish('remaining-grant', other))
        self.assert_source(receipt, self.checked(self.public(other)), jia, 'early-jia')

    def test_withdrawn_preference(self):
        (jia, yi), program = self.prepare()
        pid = program['program_id']
        self.grant('grant-jia', jia)
        self.grant('grant-yi', yi)
        self.checked(self.public(pid), 404)
        withdraw = self.withdraw('withdraw-jia', jia, 'grant-jia')
        self.assertEqual(withdraw['status'], 'applied')
        receipt = self.checked(self.publish('withdrawn-preference', pid))
        heard = self.checked(self.public(pid))
        proof = self.proof_audio(pid, 2)
        self.assert_source(receipt, heard, yi, 'grant-yi')
        self.assertEqual(heard['audio_b64'], proof['audio_b64'])
        self.assertEqual(heard['digest'], proof['digest'])
        self.assertEqual(receipt['priority'], 2)
        recovered = self.checked(self.release('GET', '/releases/withdrawn-preference'))
        self.assertEqual(recovered, receipt)
        fields = ('recording_id', 'credit', 'grant_id')
        expected = [yi['recording_id'], '周乙', 'grant-yi']
        report('v5', {'program_id': pid, 'ordered_sources': [jia['recording_id'], yi['recording_id']],
                      'withdrawal_status': withdraw['status']}, expected, [heard[x] for x in fields],
               expected, [recovered[x] for x in fields], ['release/publication.py', 'release/listening.py',
                                                          'release/recovery.py'],
               'First source has a confirmed withdrawal; only the second source still has a grant.')

    def test_withdrawal_before_commit(self):
        entered, proceed = Event(), Event()
        selections = []

        def hold_after_selection(recording_id):
            selections.append(recording_id)
            entered.set()
            if not proceed.wait(6):
                raise RuntimeError('publication test gate timed out')

        self.reopen(ReleaseHooks(after_selection=hold_after_selection))
        (jia, yi), program = self.prepare()
        pid = program['program_id']
        self.grant('grant-jia', jia)
        self.grant('grant-yi', yi)
        with ThreadPoolExecutor(max_workers=1) as executor:
            running = executor.submit(self.publish, 'overlap', pid)
            try:
                self.assertTrue(entered.wait(4))
                self.assertEqual(selections, [jia['recording_id']])
                self.checked(self.public(pid), 404)
                self.assertEqual(self.withdraw('withdraw-jia', jia, 'grant-jia')['status'], 'applied')
                self.assertEqual(self.checked(self.release('GET', '/releases/overlap'))['status'], 'pending')
                self.checked(self.public(pid), 404)
            finally:
                proceed.set()
            receipt = self.checked(running.result(timeout=6))
        self.assert_source(receipt, self.checked(self.public(pid)), yi, 'grant-yi')
        self.assertEqual(self.checked(self.release('GET', '/releases/overlap')), receipt)

    def test_no_eligible_candidate(self):
        (jia, yi), program = self.prepare()
        pid = program['program_id']
        privates = [self.proof_audio(pid, priority) for priority in (1, 2)]
        for suffix, record in (('jia', jia), ('yi', yi)):
            grant = self.grant(f'grant-{suffix}', record)
            self.assertEqual(self.withdraw(f'withdraw-{suffix}', record, grant['grant_id'])['status'], 'applied')
        result = self.checked(self.publish('no-choice', pid), 422)
        self.assertEqual(result, {'error': 'no_eligible_source'})
        self.checked(self.public(pid), 404)
        status = self.checked(self.release('GET', '/releases/no-choice'))
        self.assertEqual(status, {'status': 'no_eligible_source', 'program_id': pid, 'request_id': 'no-choice'})
        self.assertEqual([self.proof_audio(pid, priority) for priority in (1, 2)], privates)
