from base64 import b64decode
from dataclasses import dataclass
from http.client import HTTPException
from typing import Callable

from consent.grants import Grant
from consent.history import ConsentAction
from editorial.proofs import Proof, ProofEntry
from festival_http import (ApiError, DropResponse, FestivalServer, JsonHandler, ServiceContext, identifier,
                           initialize, path_id, positive_id, request_json, run_service)
from release.listening import listen
from release.publication import PublicationStore, publish_program
from release.receipts import ReleaseReceipt, receipt_payload
from release.recovery import lookup_release
from staging.preparation import stage_program
from staging.proof_listening import read_proof_audio
from staging.references import StageStore


@dataclass(frozen=True)
class ReleaseHooks:
    before_apply: Callable[[ConsentAction], None] | None = None
    before_verification: Callable[[ProofEntry, bytes], bytes] | None = None
    after_registration: Callable[[str], None] | None = None
    after_selection: Callable[[int | None], None] | None = None
    drop_after_commit: Callable[[ReleaseReceipt], bool] | None = None


class ReleaseHandler(JsonHandler):
    def public_route(self, method, parts):
        return method == 'GET' and (parts == ('health',) or len(parts) == 2 and parts[0] == 'listen')

    def editorial_get(self, path):
        try:
            status, result = request_json(self.context.peer_url, 'GET', path, desk_key=self.context.desk_key)
        except (OSError, HTTPException, ValueError) as error:
            raise ApiError(503, 'editorial_unavailable') from error
        if status == 404:
            raise ApiError(404, result['error'])
        if status != 200:
            raise ApiError(503, 'editorial_unavailable')
        return result

    def proof(self, program_id):
        result = self.editorial_get(f'/programs/{program_id}')
        return Proof.from_payload(result)

    def dispatch(self, db, method, parts, data):
        publications = PublicationStore(db)
        match method, parts:
            case 'GET', ('health',):
                return 200, {'ready': True}
            case 'POST', ('internal', 'consent'):
                return 200, self.receive_consent(ConsentAction.from_payload(data))
            case 'POST', ('stages',):
                proof = self.proof(positive_id(data['program_id']))
                originals = self.fetch_originals(proof)
                references = stage_program(StageStore(db), proof, originals,
                                           before_verification=self.context.hooks.before_verification)
                return 200, {'program_id': proof.program_id, 'entries': [ref.description() for ref in references]}
            case 'GET', ('proofs', program_id, priority):
                audio = read_proof_audio(StageStore(db), self.proof(path_id(program_id)), path_id(priority))
                return 200, audio.payload()
            case 'POST', ('releases',):
                request_id = identifier(data['request_id'])
                program_id = positive_id(data['program_id'])
                return 200, self.publish(publications, request_id, program_id)
            case 'GET', ('releases', request_id):
                return 200, lookup_release(publications, identifier(request_id))
            case 'GET', ('listen', public_id):
                return 200, listen(publications, identifier(public_id)).payload()
            case _:
                raise ApiError(404, 'unknown_route')

    def fetch_originals(self, proof):
        originals = {}
        for entry in proof.entries:
            recording_id = entry.candidate.recording_id
            if recording_id in originals:
                continue
            try:
                source = self.editorial_get(f'/recordings/{recording_id}')
            except ApiError as error:
                if error.status == 404:
                    continue
                raise
            if (source['recording_id'], source['actor_id'], source['credit']) == (
                    recording_id, entry.attribution.actor_id, entry.attribution.credit):
                originals[recording_id] = b64decode(source['audio_b64'], validate=True)
        return originals

    def receive_consent(self, action):
        hook = self.context.hooks.before_apply
        if hook is not None:
            hook(action)
        return {'action_id': action.action_id, 'status': 'received'}

    def publish(self, store, request_id, program_id):
        store.check_binding(request_id, program_id)
        try:
            plan = self.editorial_get(f'/internal/release-plan/{program_id}')
        except ApiError as error:
            if error.status != 503:
                raise
            existing = store.get_by_request(request_id)
            if existing is None:
                raise
            if existing.receipt.program_id != program_id:
                raise ApiError(409, 'request_conflict')
            return receipt_payload(existing.receipt)
        proof = Proof.from_payload(plan['proof'])
        grants = {row['recording_id']: Grant.from_row(row) for row in plan['grants']}

        def refresh_plan(current_program_id):
            latest = self.editorial_get(f'/internal/release-plan/{current_program_id}')
            return (Proof.from_payload(latest['proof']),
                    {row['recording_id']: Grant.from_row(row) for row in latest['grants']})

        hooks = self.context.hooks
        receipt, created = publish_program(store, request_id, proof, grants,
                                           after_registration=hooks.after_registration,
                                           after_selection=hooks.after_selection,
                                           refresh_plan=refresh_plan)
        if created and hooks.drop_after_commit is not None and hooks.drop_after_commit(receipt):
            raise DropResponse()
        return receipt_payload(receipt)


def serve_release(database, editorial_url, desk_key, *, port=0, hooks=None):
    initialize(database, StageStore.schema, PublicationStore.schema)
    context = ServiceContext(database, editorial_url, desk_key, ReleaseHooks() if hooks is None else hooks)
    return FestivalServer(port, ReleaseHandler, context)


if __name__ == '__main__':
    run_service(serve_release)
