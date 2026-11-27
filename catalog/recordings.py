from dataclasses import asdict, dataclass

from catalog.audio_metadata import AudioMetadata
from catalog.credits import RecordingCredit


@dataclass(frozen=True)
class Recording:
    recording_id: int
    attribution: RecordingCredit
    metadata: AudioMetadata
    audio: bytes

    def description(self):
        return {'recording_id': self.recording_id, **asdict(self.attribution), **asdict(self.metadata)}


class RecordingStore:
    schema = '''
        CREATE TABLE IF NOT EXISTS recordings (
            recording_id INTEGER PRIMARY KEY,
            actor_id TEXT NOT NULL,
            credit TEXT NOT NULL,
            sample_rate INTEGER NOT NULL,
            channels INTEGER NOT NULL,
            sample_width INTEGER NOT NULL,
            frame_count INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            audio BLOB NOT NULL
        );
    '''

    def __init__(self, db):
        self.db = db

    def insert(self, attribution, metadata, audio):
        cursor = self.db.execute('''
            INSERT INTO recordings (actor_id, credit, sample_rate, channels, sample_width,
                                    frame_count, duration_ms, audio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (attribution.actor_id, attribution.credit, metadata.sample_rate, metadata.channels,
              metadata.sample_width, metadata.frame_count, metadata.duration_ms, audio))
        return Recording(cursor.lastrowid, attribution, metadata, audio)

    def get(self, recording_id):
        row = self.db.execute('SELECT * FROM recordings WHERE recording_id = ?', (recording_id,)).fetchone()
        if row is None:
            return None
        credit = RecordingCredit(row['actor_id'], row['credit'])
        metadata = AudioMetadata(row['sample_rate'], row['channels'], row['sample_width'],
                                 row['frame_count'], row['duration_ms'])
        return Recording(row['recording_id'], credit, metadata, row['audio'])
