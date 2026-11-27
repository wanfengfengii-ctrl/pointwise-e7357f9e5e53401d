from consent.grants import Grant
from consent.history import PURPOSE


def find_eligible_grant(db, recording_id, purpose=PURPOSE):
    row = db.execute('''
        SELECT grant_row.* FROM grants AS grant_row
        WHERE grant_row.recording_id = ? AND grant_row.purpose = ?
          AND NOT EXISTS (
              SELECT 1 FROM withdrawals WHERE withdrawals.grant_id = grant_row.grant_id
          )
        ORDER BY grant_row.sequence DESC LIMIT 1
    ''', (recording_id, purpose)).fetchone()
    return None if row is None else Grant.from_row(row)
