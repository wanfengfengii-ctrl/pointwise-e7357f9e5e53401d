"""Reproduce the two publication failures through the festival HTTP services."""
from concurrent.futures import ThreadPoolExecutor
from http.client import RemoteDisconnected
from threading import Event
import unittest

from festival_http import DropResponse
from release.http_api import ReleaseHooks
from tests.support import HttpCase


MARKER = 'FESTIVAL_FIRST_RELEASE_MISMATCH'


def source(row):
    return tuple(row[key] for key in ('recording_id', 'actor_id', 'credit', 'grant_id'))


def expected_source(record, grant_id):
    return (record['recording_id'], record['actor_id'], record['credit'], grant_id)


class Incident(HttpCase):
    def prepare_sources(self):
        records, program = self.prepare()
        pid = program['program_id']
        clips = [self.proof_audio(pid, order) for order in (1, 2)]
        self.assertEqual(clips[0]['audio_b64'], clips[1]['audio_b64'])
        for record, grant_id in zip(records, ('jia-grant', 'yi-grant')):
            self.assertEqual(self.grant(grant_id, record)['status'], 'applied')
        self.checked(self.public(pid), 404)
        return records, pid, clips[0]['audio_b64']

    def withdrawal_during_release(self, drop_notice):
        entered, proceed = Event(), Event()
        selected = []

        def pause(recording_id):
            selected.append(recording_id)
            entered.set()
            if not proceed.wait(10):
                raise RuntimeError('publication gate timed out')

        def receive(action):
            if drop_notice and action.action_id == 'jia-withdrawal':
                raise DropResponse()

        self.reopen(ReleaseHooks(after_selection=pause, before_apply=receive))
        (jia, yi), pid, audio = self.prepare_sources()
        withdrawal = self.action('jia-withdrawal', jia, 'jia-grant')
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(self.publish, 'night-slot', pid)
            try:
                self.assertTrue(entered.wait(4), 'publication gate not reached')
                self.assertEqual(selected, [jia['recording_id']])
                self.checked(self.public(pid), 404)
                status, result = self.editor('POST', '/consent', withdrawal)
                self.assertIn(status, (200, 202) if drop_notice else (200,), result)
                confirmed = status == 200
                self.assertEqual(result['status'], 'applied' if confirmed else 'pending')
                self.assertEqual(self.checked(self.editor('GET', '/consent/jia-withdrawal'), status), result)
                self.checked(self.public(pid), 404)
            finally:
                proceed.set()
            receipt = self.checked(pending.result(timeout=6))
        heard = self.checked(self.public(pid))
        self.assertEqual(heard, {**receipt, 'audio_b64': audio})
        self.assertEqual(self.checked(self.release('GET', '/releases/night-slot')), receipt)
        first = expected_source(jia, 'jia-grant')
        fallback = expected_source(yi, 'yi-grant')
        if confirmed and source(receipt) == first:
            print(f'{MARKER} withdrawal-first drop_notice={drop_notice} actual={first!r} expected={fallback!r}', flush=True)
        if confirmed:
            self.assertEqual(source(receipt), fallback)
        else:
            self.assertIn(source(receipt), (first, fallback))

    def test_withdrawal_first(self):
        self.withdrawal_during_release(False)

    def test_notice_interrupted(self):
        self.withdrawal_during_release(True)

    def test_publication_first(self):
        self.reopen(ReleaseHooks(drop_after_commit=lambda receipt: receipt.request_id == 'night-slot'))
        (jia, yi), pid, audio = self.prepare_sources()
        with self.assertRaises(RemoteDisconnected):
            self.publish('night-slot', pid)
        first_public = self.checked(self.public(pid))
        first = self.checked(self.release('GET', '/releases/night-slot'))
        self.assertEqual(source(first), expected_source(jia, 'jia-grant'))
        self.assertEqual(first_public, {**first, 'audio_b64': audio})
        self.assertEqual(self.withdraw('jia-withdrawal', jia, 'jia-grant')['status'], 'applied')
        self.reopen()
        self.assertEqual(self.checked(self.release('GET', '/releases/night-slot')), first)
        retried = self.checked(self.publish('night-slot', pid))
        heard = self.checked(self.public(pid))
        stored = self.checked(self.release('GET', '/releases/night-slot'))
        fallback = expected_source(yi, 'yi-grant')
        if source(retried) == source(heard) == source(stored) == fallback and heard['audio_b64'] == audio:
            print(f'{MARKER} publication-first actual={fallback!r} expected={source(first)!r}', flush=True)
        self.assertEqual(retried, first)
        self.assertEqual(heard, first_public)
        self.assertEqual(stored, first)


if __name__ == '__main__':
    unittest.main(verbosity=2)
