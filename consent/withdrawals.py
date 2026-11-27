from dataclasses import dataclass

from consent.grants import find_grant
from consent.history import ConsentAction, ConsentHistory
from festival_http import ApiError


@dataclass(frozen=True)
class Withdrawal:
    action_id: str
    grant_id: str


WITHDRAWAL_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS withdrawals (
        action_id TEXT PRIMARY KEY,
        grant_id TEXT NOT NULL REFERENCES grants(grant_id)
    );
    CREATE INDEX IF NOT EXISTS withdrawals_by_grant ON withdrawals(grant_id);
'''


def _check_scope(action, grant):
    if (grant.actor_id, grant.recording_id, grant.purpose) != (action.actor_id, action.recording_id, action.purpose):
        raise ApiError(422, 'grant_scope_mismatch')


def request_withdrawal(history: ConsentHistory, action: ConsentAction):
    original = history.get_result(action.grant_id)
    if original is None or original['kind'] != 'grant':
        raise ApiError(422, 'unknown_grant')
    _check_scope(action, ConsentAction.from_payload(original))
    return history.remember(action)


def resolve_withdrawal(db, action: ConsentAction):
    grant = find_grant(db, action.grant_id)
    if grant is None:
        raise ApiError(409, 'grant_not_applied')
    _check_scope(action, grant)
    applied = Withdrawal(action.action_id, action.grant_id)
    db.execute('INSERT INTO withdrawals VALUES (?, ?)', (applied.action_id, applied.grant_id))
    return applied
