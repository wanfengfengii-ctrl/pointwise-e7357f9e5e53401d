from dataclasses import asdict, dataclass
import json

from editorial.candidates import Candidate, assemble_candidates
from festival_http import ApiError


@dataclass(frozen=True)
class ProgramDraft:
    draft_id: int
    title: str
    candidates: list

    def payload(self):
        return asdict(self)


@dataclass(frozen=True)
class FrozenProgram:
    program_id: int
    title: str
    candidates: tuple[Candidate, ...]


class ProgramStore:
    schema = '''
        CREATE TABLE IF NOT EXISTS drafts (
            draft_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            candidates_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS programs (
            program_id INTEGER PRIMARY KEY,
            draft_id INTEGER NOT NULL REFERENCES drafts(draft_id),
            title TEXT NOT NULL,
            candidates_json TEXT NOT NULL
        );
    '''

    def __init__(self, db):
        self.db = db

    def save_draft(self, title, candidates, draft_id=None):
        if not isinstance(title, str) or not title.strip():
            raise ValueError('missing program title')
        if not isinstance(candidates, list) or not candidates or any(not isinstance(x, dict) for x in candidates):
            raise ValueError('expected a nonempty candidate list')
        encoded = json.dumps(candidates, ensure_ascii=False)
        if draft_id is None:
            result = self.db.execute('INSERT INTO drafts (title, candidates_json) VALUES (?, ?)', (title, encoded))
            draft_id = result.lastrowid
        else:
            result = self.db.execute('UPDATE drafts SET title = ?, candidates_json = ? WHERE draft_id = ?',
                                     (title, encoded, draft_id))
            if not result.rowcount:
                raise ApiError(404, 'unknown_draft')
        return ProgramDraft(draft_id, title, candidates)

    def get_draft(self, draft_id):
        row = self.db.execute('SELECT title, candidates_json FROM drafts WHERE draft_id = ?', (draft_id,)).fetchone()
        if row is None:
            raise ApiError(404, 'unknown_draft')
        return ProgramDraft(draft_id, row['title'], json.loads(row['candidates_json']))

    def save_frozen(self, draft, candidates):
        encoded = json.dumps([candidate.payload() for candidate in candidates])
        cursor = self.db.execute('INSERT INTO programs (draft_id, title, candidates_json) VALUES (?, ?, ?)',
                                 (draft.draft_id, draft.title, encoded))
        return FrozenProgram(cursor.lastrowid, draft.title, candidates)

    def get_frozen(self, program_id):
        row = self.db.execute('SELECT title, candidates_json FROM programs WHERE program_id = ?',
                              (program_id,)).fetchone()
        if row is None:
            raise ApiError(404, 'unknown_program')
        candidates = tuple(Candidate.from_payload(item) for item in json.loads(row['candidates_json']))
        return FrozenProgram(program_id, row['title'], candidates)


def freeze_program(store: ProgramStore, recordings, draft_id):
    draft = store.get_draft(draft_id)
    candidates = assemble_candidates(draft.candidates, recordings)
    return store.save_frozen(draft, candidates)
