from festival_http import ApiError, transaction
from release.publication import PublicationStore
from release.receipts import receipt_payload


def lookup_release(store: PublicationStore, request_id):
    with transaction(store.db, immediate=False):
        request = store.get_request(request_id)
        if request is None:
            raise ApiError(404, 'unknown_release')
        publication = store.get_by_request(request_id)
        if publication is not None:
            return receipt_payload(publication.receipt)
        return {'request_id': request_id, 'program_id': request.program_id, 'status': request.status}
