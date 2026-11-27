from dataclasses import dataclass
import json
import sqlite3

from editorial.proofs import Proof
from festival_http import ApiError, database_busy, transaction
from release.receipts import ReleaseReceipt, make_receipt, receipt_payload, restore_receipt
from staging.references import StageStore


@dataclass(frozen=True)
class Publication:
    receipt: ReleaseReceipt
    audio: bytes


@dataclass(frozen=True)
class ReleaseRequest:
    request_id: str
    program_id: int
    status: str


class PublicationStore:
    schema = '''
        CREATE TABLE IF NOT EXISTS release_requests (
            request_id TEXT PRIMARY KEY,
            program_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'no_eligible_source', 'published'))
        );
        CREATE TABLE IF NOT EXISTS publications (
            request_id TEXT PRIMARY KEY REFERENCES release_requests(request_id),
            public_id TEXT NOT NULL UNIQUE,
            receipt_json TEXT NOT NULL,
            audio BLOB NOT NULL
        );
    '''

    def __init__(self, db):
        self.db = db

    def get_request(self, request_id):
        row = self.db.execute('SELECT * FROM release_requests WHERE request_id = ?', (request_id,)).fetchone()
        return None if row is None else ReleaseRequest(row['request_id'], row['program_id'], row['status'])

    def check_binding(self, request_id, program_id):
        request = self.get_request(request_id)
        if request is not None and request.program_id != program_id:
            raise ApiError(409, 'request_conflict')
        return request

    def register(self, request_id, program_id):
        if self.check_binding(request_id, program_id) is None:
            self.db.execute('INSERT INTO release_requests VALUES (?, ?, ?)', (request_id, program_id, 'pending'))

    @staticmethod
    def _restore(row):
        if row is None:
            return None
        return Publication(restore_receipt(row['receipt_json']), row['audio'])

    def get_publication(self, public_id):
        row = self.db.execute('SELECT receipt_json, audio FROM publications WHERE public_id = ?', (public_id,)).fetchone()
        return self._restore(row)

    def get_by_request(self, request_id):
        row = self.db.execute('SELECT receipt_json, audio FROM publications WHERE request_id = ?', (request_id,)).fetchone()
        return self._restore(row)

    def set_status(self, request_id, status):
        self.db.execute('UPDATE release_requests SET status = ? WHERE request_id = ?', (status, request_id))

    def establish(self, publication):
        receipt = publication.receipt
        encoded = json.dumps(receipt_payload(receipt), ensure_ascii=False)
        self.db.execute('''
            INSERT INTO publications VALUES (?, ?, ?, ?)
            ON CONFLICT (request_id) DO UPDATE SET receipt_json = excluded.receipt_json, audio = excluded.audio
        ''', (receipt.request_id, receipt.public_id, encoded, publication.audio))
        self.set_status(receipt.request_id, 'published')


def _choose(db, proof, grants):
    staged = StageStore(db)
    for entry in proof.entries:
        reference = staged.get_verified(proof.program_id, entry)
        if reference is None:
            continue
        grant = grants.get(entry.candidate.recording_id)
        if grant is not None and grant.actor_id == entry.attribution.actor_id:
            return reference, grant
    return None


def _decide(store, request_id, proof, grants, after_selection):
    public_id = f'preview-{proof.program_id}'
    with transaction(store.db, immediate=False):
        previous = store.get_by_request(request_id)
        if previous is None and store.get_publication(public_id) is not None:
            raise ApiError(409, 'program_already_published')
        choice = _choose(store.db, proof, grants)
        if after_selection is not None:
            selected_id = None if choice is None else choice[0].entry.candidate.recording_id
            after_selection(selected_id)
        if choice is None:
            if previous is not None:
                return previous.receipt, False
            store.set_status(request_id, 'no_eligible_source')
            return None, False
        reference, grant = choice
        receipt = make_receipt(request_id, public_id, reference, grant)
        store.establish(Publication(receipt, reference.clip.audio))
        return receipt, previous is None


def publish_program(store: PublicationStore, request_id, proof: Proof, grants, *,
                    after_registration=None, after_selection=None):
    with transaction(store.db):
        store.register(request_id, proof.program_id)
        established = store.get_by_request(request_id) is not None
    if not established and after_registration is not None:
        after_registration(request_id)
    for attempt in range(4):
        try:
            # A WAL read snapshot can only be promoted if another writer has not superseded it.
            observer = after_selection if attempt == 0 else None
            receipt, created = _decide(store, request_id, proof, grants, observer)
        except sqlite3.OperationalError as error:
            if not database_busy(error):
                raise
            continue
        if receipt is None:
            raise ApiError(422, 'no_eligible_source')
        return receipt, created
    raise ApiError(503, 'release_busy')
