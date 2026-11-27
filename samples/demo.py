from base64 import b64decode, b64encode
from contextlib import contextmanager
from http.client import RemoteDisconnected
from io import BytesIO
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import wave

from editorial.http_api import serve_editorial
from festival_http import request_json, running
from release.http_api import ReleaseHooks, serve_release


DESK_KEY = 'festival-sample'


def sample_wave(rate=8000, duration_ms=400, channels=1):
    samples = bytearray()
    for i in range(rate * duration_ms // 1000):
        value = i % 257 - 128
        samples.extend(struct.pack('<h', value))
        if channels == 2:
            samples.extend(struct.pack('<h', -value))
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(samples)
    return buffer.getvalue()


@contextmanager
def local_pair(directory, hooks=None):
    with serve_editorial(directory / 'editorial.sqlite3', '', DESK_KEY) as editorial:
        with serve_release(directory / 'release.sqlite3', editorial.url, DESK_KEY, hooks=hooks) as release:
            editorial.context.peer_url = release.url
            with running(editorial), running(release):
                yield editorial.url, release.url


def checked(url, method, path, body=None, *, expected=200, public=False):
    status, result = request_json(url, method, path, body, desk_key=None if public else DESK_KEY)
    if status != expected:
        raise RuntimeError(f'{method} {path}: expected {expected}, got {status} ({result.get("error")})')
    return result


def prepare_shift(editorial, release, plan):
    wav = sample_wave(plan['sample_rate'], plan['duration_ms'])
    encoded = b64encode(wav).decode('ascii')
    candidates = []
    actions = []
    for actor in plan['actors']:
        original = checked(editorial, 'POST', '/recordings', {**actor, 'audio_b64': encoded}, expected=201)
        if original['duration_ms'] != plan['duration_ms']:
            raise RuntimeError('unexpected sample duration')
        recording_id = original['recording_id']
        candidates.append({'recording_id': recording_id, 'start_ms': plan['start_ms'], 'end_ms': plan['end_ms']})
        actions.append({'action_id': f'grant-{recording_id}', 'kind': 'grant', 'actor_id': actor['actor_id'],
                        'recording_id': recording_id, 'purpose': 'preview_release'})
    programs = []
    for title in plan['titles']:
        draft = checked(editorial, 'POST', '/drafts', {'title': title, 'candidates': candidates}, expected=201)
        program = checked(editorial, 'POST', '/programs/freeze', {'draft_id': draft['draft_id']}, expected=201)
        program_id = program['program_id']
        programs.append(program_id)
        checked(release, 'POST', '/stages', {'program_id': program_id})
        for priority, candidate in enumerate(candidates, 1):
            clip = checked(release, 'GET', f'/proofs/{program_id}/{priority}')
            with wave.open(BytesIO(b64decode(clip['audio_b64'])), 'rb') as pcm:
                if (pcm.getnframes(), clip['recording_id']) != (plan['expected_frames'], candidate['recording_id']):
                    raise RuntimeError('proof does not match the shift plan')
        checked(release, 'GET', f'/listen/preview-{program_id}', expected=404, public=True)
    for action in actions:
        checked(editorial, 'POST', '/consent', action)
    return programs, actions


def main():
    plan = json.loads(Path(__file__).with_name('shift.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='festival-shift-') as directory:
        location = Path(directory)
        hooks = ReleaseHooks(drop_after_commit=lambda receipt: receipt.request_id == 'night-original')
        with local_pair(location, hooks) as (editorial, release):
            (first, second), (jia, yi) = prepare_shift(editorial, release, plan)
            original = {'request_id': 'night-original', 'program_id': first}
            try:
                checked(release, 'POST', '/releases', original)
            except RemoteDisconnected:
                pass
            else:
                raise RuntimeError('expected the original response to be lost')
            first_audio = checked(release, 'GET', f'/listen/preview-{first}', public=True)
            revoke = {**jia, 'grant_id': jia['action_id'], 'action_id': 'withdraw-jia', 'kind': 'withdraw'}
            withdrawal = checked(editorial, 'POST', '/consent', revoke)
            fallback = checked(release, 'POST', '/releases', {'request_id': 'night-fallback', 'program_id': second})
            second_audio = checked(release, 'GET', f'/listen/preview-{second}', public=True)
            if (first_audio['recording_id'], fallback['recording_id']) != (jia['recording_id'], yi['recording_id']):
                raise RuntimeError('first publication or fallback has the wrong actor source')
            if second_audio['credit'] != plan['actors'][1]['credit'] or withdrawal['status'] != 'applied':
                raise RuntimeError('fallback credit or withdrawal does not match the shift')
        with local_pair(location) as (_, release):
            recovered = checked(release, 'GET', '/releases/night-original')
            retried = checked(release, 'POST', '/releases', original)
            replay = checked(release, 'GET', f'/listen/preview-{first}', public=True)
            first_receipt = {key: value for key, value in first_audio.items() if key != 'audio_b64'}
            if recovered != first_receipt or retried != recovered or replay != first_audio:
                raise RuntimeError('recovered receipt and public playback disagree')
    print(json.dumps({'withdrawal': withdrawal, 'original': recovered, 'fallback': fallback}, ensure_ascii=False))


if __name__ == '__main__':
    main()
