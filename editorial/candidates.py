from dataclasses import asdict, dataclass

from catalog.recordings import RecordingStore
from editorial.excerpts import Excerpt, FrameSpan, project_frames, validate_excerpt
from festival_http import ApiError, positive_id


@dataclass(frozen=True)
class Candidate:
    priority: int
    recording_id: int
    excerpt: Excerpt
    span: FrameSpan

    def payload(self):
        return {'priority': self.priority, 'recording_id': self.recording_id,
                **asdict(self.excerpt), **asdict(self.span)}

    @classmethod
    def from_payload(cls, body):
        return cls(body['priority'], body['recording_id'], Excerpt(body['start_ms'], body['end_ms']),
                   FrameSpan(body['start_frame'], body['end_frame']))


def assemble_candidates(rows, recordings: RecordingStore):
    candidates = []
    for priority, row in enumerate(rows, start=1):
        recording_id = positive_id(row['recording_id'])
        recording = recordings.get(recording_id)
        if recording is None:
            raise ApiError(422, 'unknown_recording', priority=priority)
        try:
            excerpt = validate_excerpt(row['start_ms'], row['end_ms'], recording.metadata)
            span = project_frames(excerpt, recording.metadata)
        except (KeyError, ValueError) as error:
            raise ApiError(422, 'invalid_excerpt', priority=priority) from error
        candidates.append(Candidate(priority, recording_id, excerpt, span))
    return tuple(candidates)
