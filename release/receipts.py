from dataclasses import asdict, dataclass
import json

from catalog.credits import RecordingCredit


@dataclass(frozen=True)
class ReleaseReceipt:
    request_id: str
    program_id: int
    public_id: str
    recording_id: int
    priority: int
    start_ms: int
    end_ms: int
    grant_id: str
    attribution: RecordingCredit
    digest: str


def make_receipt(request_id, public_id, reference, grant):
    candidate = reference.entry.candidate
    return ReleaseReceipt(request_id, reference.program_id, public_id, candidate.recording_id, candidate.priority,
                          candidate.excerpt.start_ms, candidate.excerpt.end_ms, grant.grant_id,
                          reference.entry.attribution, reference.clip.digest)


def receipt_payload(receipt: ReleaseReceipt):
    body = asdict(receipt)
    attribution = body.pop('attribution')
    return {'status': 'published', **body, **attribution}


def restore_receipt(encoded):
    body = json.loads(encoded)
    body.pop('status')
    attribution = RecordingCredit(body.pop('actor_id'), body.pop('credit'))
    return ReleaseReceipt(**body, attribution=attribution)
