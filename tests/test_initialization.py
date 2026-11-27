from tests.support import HttpCase


class InitializationTests(HttpCase):
    def test_restart_data(self):
        (record,), program = self.prepare((('visiting-actor', '义演演员'),), start=11, end=85)
        pid = program['program_id']
        grant = self.grant('visiting-grant', record)
        receipt = self.checked(self.publish('special-night', pid))
        withdrawal = self.withdraw('visiting-withdrawal', record, grant['grant_id'])
        original = self.checked(self.editor('GET', f'/recordings/{record["recording_id"]}'))
        public = self.checked(self.public(pid))
        proof = self.proof_audio(pid, 1)
        first_draft = self.checked(self.editor('GET', '/drafts/1'))
        for restart in (1, 2):
            with self.subTest(restart=restart):
                self.reopen()
                self.assertEqual(self.checked(self.editor('GET', f'/recordings/{record["recording_id"]}')), original)
                self.assertEqual(self.checked(self.editor('GET', '/drafts/1')), first_draft)
                self.assertEqual(self.checked(self.editor('GET', f'/programs/{pid}')), program)
                self.assertEqual(self.checked(self.editor('GET', '/consent/visiting-withdrawal')), withdrawal)
                self.assertEqual(self.checked(self.release('GET', '/releases/special-night')), receipt)
                self.assertEqual(self.checked(self.public(pid)), public)
                self.assertEqual(self.proof_audio(pid, 1), proof)
        fresh = self.freeze([record['recording_id']])['program_id']
        self.stage(fresh)
        self.assertEqual(self.checked(self.publish('after-withdrawal', fresh), 422)['error'], 'no_eligible_source')
        self.checked(self.public(fresh), 404)
