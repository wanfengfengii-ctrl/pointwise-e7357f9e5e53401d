from dataclasses import asdict, dataclass

from catalog.credits import RecordingCredit
from catalog.recordings import RecordingStore
from editorial.candidates import Candidate
from editorial.programs import FrozenProgram


@dataclass(frozen=True)
class ProofEntry:
    candidate: Candidate
    attribution: RecordingCredit

    def payload(self):
        return {**self.candidate.payload(), **asdict(self.attribution)}

    @classmethod
    def from_payload(cls, body):
        return cls(Candidate.from_payload(body), RecordingCredit(body['actor_id'], body['credit']))


@dataclass(frozen=True)
class Proof:
    program_id: int
    title: str
    entries: tuple[ProofEntry, ...]

    def payload(self):
        return {'program_id': self.program_id, 'title': self.title,
                'entries': [entry.payload() for entry in self.entries]}

    @classmethod
    def from_payload(cls, body):
        return cls(body['program_id'], body['title'], tuple(ProofEntry.from_payload(entry) for entry in body['entries']))

    def entry_at(self, priority):
        if 1 <= priority <= len(self.entries):
            return self.entries[priority - 1]
        return None


def build_proof(program: FrozenProgram, recordings: RecordingStore):
    entries = []
    for candidate in program.candidates:
        recording = recordings.get(candidate.recording_id)
        if recording is None:
            raise RuntimeError('frozen program has no original recording')
        entries.append(ProofEntry(candidate, recording.attribution))
    return Proof(program.program_id, program.title, tuple(entries))
