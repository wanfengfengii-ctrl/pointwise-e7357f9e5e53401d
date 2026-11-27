from base64 import b64encode
from dataclasses import dataclass

from festival_http import ApiError
from release.publication import Publication, PublicationStore
from release.receipts import receipt_payload


@dataclass(frozen=True)
class ListeningResult:
    publication: Publication

    def payload(self):
        encoded = b64encode(self.publication.audio).decode('ascii')
        return {**receipt_payload(self.publication.receipt), 'audio_b64': encoded}


def listen(store: PublicationStore, public_id):
    publication = store.get_publication(public_id)
    if publication is None:
        raise ApiError(404, 'not_public')
    return ListeningResult(publication)
