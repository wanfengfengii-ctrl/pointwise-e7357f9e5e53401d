from dataclasses import dataclass

from catalog.recordings import Recording
from consent.history import ConsentAction
from festival_http import ApiError


@dataclass(frozen=True)
class Grant:
    sequence: int
    grant_id: str
    actor_id: str
    recording_id: int
    purpose: str

    @classmethod
    def from_row(cls, row):
        return cls(row['sequence'], row['grant_id'], row['actor_id'], row['recording_id'], row['purpose'])


GRANT_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS grants (
        sequence INTEGER PRIMARY KEY,
        grant_id TEXT NOT NULL UNIQUE,
        actor_id TEXT NOT NULL,
        recording_id INTEGER NOT NULL,
        purpose TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS grants_by_source ON grants(recording_id, purpose, sequence DESC);
'''


def validate_owner(action: ConsentAction, recording: Recording | None):
    if recording is None or recording.attribution.actor_id != action.actor_id:
        raise ApiError(422, 'recording_owner_mismatch')


def record_grant(db, action: ConsentAction):
    db.execute('INSERT INTO grants (grant_id, actor_id, recording_id, purpose) VALUES (?, ?, ?, ?)',
               (action.grant_id, action.actor_id, action.recording_id, action.purpose))
    return find_grant(db, action.grant_id)


def find_grant(db, grant_id):
    row = db.execute('SELECT * FROM grants WHERE grant_id = ?', (grant_id,)).fetchone()
    return None if row is None else Grant.from_row(row)
