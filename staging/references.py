from dataclasses import dataclass
from hashlib import sha256
import json

from editorial.proofs import ProofEntry
from staging.verification import VerifiedClip


@dataclass(frozen=True)
class StageReference:
    program_id: int
    entry: ProofEntry
    clip: VerifiedClip

    def description(self):
        return {'program_id': self.program_id, **self.entry.payload(), 'digest': self.clip.digest}


class StageStore:
    schema = '''
        CREATE TABLE IF NOT EXISTS staged_clips (
            program_id INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            entry_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('verified', 'failed')),
            digest TEXT,
            audio BLOB,
            PRIMARY KEY (program_id, priority),
            CHECK ((status = 'verified' AND digest IS NOT NULL AND audio IS NOT NULL)
                OR (status = 'failed' AND digest IS NULL AND audio IS NULL))
        );
    '''

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _identity(entry):
        return json.dumps(entry.payload(), sort_keys=True, ensure_ascii=False)

    def _save(self, program_id, entry, status, digest, audio):
        self.db.execute('''
            INSERT INTO staged_clips VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (program_id, priority) DO UPDATE SET entry_json = excluded.entry_json,
                status = excluded.status, digest = excluded.digest, audio = excluded.audio
        ''', (program_id, entry.candidate.priority, self._identity(entry), status, digest, audio))

    def save_verified(self, program_id, entry, clip):
        self._save(program_id, entry, 'verified', clip.digest, clip.audio)
        return StageReference(program_id, entry, clip)

    def get_verified(self, program_id, entry):
        row = self.db.execute('''
            SELECT entry_json, digest, audio FROM staged_clips
            WHERE program_id = ? AND priority = ? AND status = 'verified'
        ''', (program_id, entry.candidate.priority)).fetchone()
        if row is None or row['entry_json'] != self._identity(entry):
            return None
        blob = row['audio']
        if not isinstance(blob, bytes) or sha256(blob).hexdigest() != row['digest']:
            return None
        return StageReference(program_id, entry, VerifiedClip(blob, row['digest']))

    def mark_failed(self, program_id, entry):
        self._save(program_id, entry, 'failed', None, None)
