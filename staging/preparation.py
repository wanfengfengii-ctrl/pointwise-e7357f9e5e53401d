from editorial.proofs import Proof
from festival_http import ApiError, transaction
from staging.clip_bytes import extract_source_frames, render_clip
from staging.references import StageStore
from staging.verification import verify_clip


def stage_program(store: StageStore, proof: Proof, originals, *, before_verification=None):
    verified = []
    failed = []
    with transaction(store.db):
        for entry in proof.entries:
            candidate = entry.candidate
            try:
                original = originals[candidate.recording_id]
                expected = extract_source_frames(original, candidate.span)
                rendered = render_clip(expected)
                if before_verification is not None:
                    rendered = before_verification(entry, rendered)
                checked = verify_clip(rendered, expected)
            except (KeyError, ValueError):
                store.mark_failed(proof.program_id, entry)
                failed.append(candidate.priority)
            else:
                verified.append(store.save_verified(proof.program_id, entry, checked))
    if failed:
        raise ApiError(422, 'stage_failed', priorities=failed)
    return verified
