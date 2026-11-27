from base64 import b64encode
from dataclasses import dataclass

from festival_http import ApiError
from staging.references import StageReference


@dataclass(frozen=True)
class ProofAudio:
    reference: StageReference

    def payload(self):
        encoded = b64encode(self.reference.clip.audio).decode('ascii')
        return {**self.reference.description(), 'audio_b64': encoded}


def read_proof_audio(store, proof, priority):
    entry = proof.entry_at(priority)
    reference = None if entry is None else store.get_verified(proof.program_id, entry)
    if reference is None:
        raise ApiError(404, 'proof_unavailable')
    return ProofAudio(reference)
