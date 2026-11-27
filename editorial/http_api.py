from base64 import b64decode, b64encode
from dataclasses import asdict
from http.client import HTTPException

from catalog.intake import submit_recording
from catalog.recordings import RecordingStore
from consent.eligibility import find_eligible_grant
from consent.grants import GRANT_SCHEMA, find_grant, record_grant, validate_owner
from consent.history import ConsentAction, ConsentHistory
from consent.withdrawals import WITHDRAWAL_SCHEMA, request_withdrawal, resolve_withdrawal
from editorial.programs import ProgramStore, freeze_program
from editorial.proofs import build_proof
from festival_http import (ApiError, FestivalServer, JsonHandler, ServiceContext, identifier,
                           initialize, path_id, positive_id, request_json, run_service, transaction)


class EditorialHandler(JsonHandler):
    def dispatch(self, db, method, parts, data):
        recordings = RecordingStore(db)
        programs = ProgramStore(db)
        match method, parts:
            case 'POST', ('recordings',):
                encoded = data['audio_b64']
                if not isinstance(encoded, str):
                    raise ValueError('audio must be encoded as a string')
                audio = b64decode(encoded, validate=True)
                recording = submit_recording(recordings, data['actor_id'], data['credit'], audio)
                return 201, recording.description()
            case 'GET', ('recordings', identity):
                recording = recordings.get(path_id(identity))
                if recording is None:
                    raise ApiError(404, 'unknown_recording')
                return 200, {**recording.description(), 'audio_b64': b64encode(recording.audio).decode('ascii')}
            case 'POST', ('drafts',):
                draft_id = positive_id(data['draft_id']) if 'draft_id' in data else None
                draft = programs.save_draft(data['title'], data['candidates'], draft_id)
                return (201 if draft_id is None else 200), draft.payload()
            case 'GET', ('drafts', identity):
                return 200, programs.get_draft(path_id(identity)).payload()
            case 'POST', ('programs', 'freeze'):
                with transaction(db):
                    frozen = freeze_program(programs, recordings, positive_id(data['draft_id']))
                    proof = build_proof(frozen, recordings)
                return 201, proof.payload()
            case 'GET', ('programs', identity):
                frozen = programs.get_frozen(path_id(identity))
                return 200, build_proof(frozen, recordings).payload()
            case 'GET', ('internal', 'release-plan', identity):
                return 200, self.release_plan(db, programs, recordings, path_id(identity))
            case 'POST', ('consent',):
                return self.change_consent(db, recordings, ConsentAction.from_payload(data))
            case 'GET', ('consent', identity):
                result = ConsentHistory(db).get_result(identifier(identity))
                if result is None:
                    raise ApiError(404, 'unknown_consent_action')
                return (200 if result['status'] == 'applied' else 202), result
            case _:
                raise ApiError(404, 'unknown_route')

    def release_plan(self, db, programs, recordings, program_id):
        with transaction(db, immediate=False):
            proof = build_proof(programs.get_frozen(program_id), recordings)
            sources = dict.fromkeys(entry.candidate.recording_id for entry in proof.entries)
            grants = [find_eligible_grant(db, source) for source in sources]
            return {'proof': proof.payload(), 'grants': [asdict(grant) for grant in grants if grant is not None]}

    def change_consent(self, db, recordings, action):
        history = ConsentHistory(db)
        with transaction(db):
            existing = history.check(action)
            if existing is not None and existing['status'] == 'applied':
                return 200, existing
            validate_owner(action, recordings.get(action.recording_id))
            if action.kind == 'withdraw':
                pending = request_withdrawal(history, action)
            else:
                pending = history.remember(action)
        try:
            status, result = request_json(self.context.peer_url, 'POST', '/internal/consent', action.payload(),
                                          desk_key=self.context.desk_key)
        except (OSError, HTTPException, ValueError):
            status, result = 503, {}
        delivered = status == 200 and result == {'action_id': action.action_id, 'status': 'received'}
        if status == 409 and result.get('error') == 'consent_action_conflict':
            raise ApiError(409, 'consent_action_conflict')
        if not delivered and not (status == 503 and action.kind == 'withdraw'):
            latest = history.get_result(action.action_id) or pending
            return (200 if latest['status'] == 'applied' else 202), latest
        with transaction(db):
            latest = history.check(action)
            if latest['status'] == 'applied':
                return 200, latest
            if action.kind == 'grant':
                record_grant(db, action)
            else:
                if find_grant(db, action.grant_id) is None:
                    return 202, latest
                resolve_withdrawal(db, action)
            return 200, history.record_result(action, {**action.payload(), 'status': 'applied'})


def serve_editorial(database, release_url, desk_key, *, port=0):
    initialize(database, RecordingStore.schema, ProgramStore.schema, ConsentHistory.schema,
               GRANT_SCHEMA, WITHDRAWAL_SCHEMA)
    return FestivalServer(port, EditorialHandler, ServiceContext(database, release_url, desk_key))


if __name__ == '__main__':
    run_service(serve_editorial)
