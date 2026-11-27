from dataclasses import asdict, dataclass
import json

from catalog.credits import make_credit
from festival_http import ApiError, identifier, positive_id


PURPOSE = 'preview_release'


@dataclass(frozen=True)
class ConsentAction:
    action_id: str
    kind: str
    actor_id: str
    recording_id: int
    purpose: str
    grant_id: str

    @classmethod
    def from_payload(cls, body):
        action_id = identifier(body['action_id'])
        kind = body['kind']
        if kind not in ('grant', 'withdraw') or body['purpose'] != PURPOSE:
            raise ValueError('invalid consent kind or purpose')
        actor_id = body['actor_id']
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError('missing actor identity')
        recording_id = positive_id(body['recording_id'])
        if kind == 'grant':
            grant_id = identifier(body.get('grant_id', action_id))
            if grant_id != action_id:
                raise ValueError('grant identity must match its action')
        else:
            grant_id = identifier(body['grant_id'])
        return cls(action_id, kind, actor_id, recording_id, PURPOSE, grant_id)

    def payload(self):
        return asdict(self)


class ConsentHistory:
    schema = '''
        CREATE TABLE IF NOT EXISTS consent_actions (
            action_id TEXT PRIMARY KEY,
            action_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'applied'))
        );
    '''

    def __init__(self, db):
        self.db = db

    def get_result(self, action_id):
        row = self.db.execute('SELECT action_json, status FROM consent_actions WHERE action_id = ?',
                              (action_id,)).fetchone()
        if row is None:
            return None
        return {**json.loads(row['action_json']), 'status': row['status']}

    def check(self, action):
        result = self.get_result(action.action_id)
        if result is not None and ConsentAction.from_payload(result) != action:
            raise ApiError(409, 'consent_action_conflict')
        return result

    def remember(self, action):
        existing = self.check(action)
        if existing is not None:
            return existing
        encoded = json.dumps(action.payload(), ensure_ascii=False)
        self.db.execute('INSERT INTO consent_actions VALUES (?, ?, ?)', (action.action_id, encoded, 'pending'))
        return {**action.payload(), 'status': 'pending'}

    def record_result(self, action, confirmation):
        if confirmation != {**action.payload(), 'status': 'applied'}:
            raise ValueError('consent confirmation does not match the action')
        self.remember(action)
        self.db.execute("UPDATE consent_actions SET status = 'applied' WHERE action_id = ?", (action.action_id,))
        return self.get_result(action.action_id)
