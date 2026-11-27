from dataclasses import dataclass


@dataclass(frozen=True)
class RecordingCredit:
    actor_id: str
    credit: str


def make_credit(actor_id, credit):
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError('missing actor identity')
    if not isinstance(credit, str) or not credit.strip():
        raise ValueError('missing original credit')
    return RecordingCredit(actor_id, credit)
