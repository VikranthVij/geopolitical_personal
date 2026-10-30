"""Read-only audit SQL gate, independent of any database connection."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase1_shadow_audit import SelectOnly


class ConnectionStub:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, params):
        self.calls.append((sql, params))
        return 'read result'


class ShadowAuditSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_mutating_multistatement_and_locking_sql_rejected_before_execution(self):
        raw = ConnectionStub()
        q = SelectOnly(raw)
        for sql in ['UPDATE incidents SET title=title', 'DELETE FROM claims',
                    'INSERT INTO sources(name) VALUES(NULL)', 'CALL procedure()',
                    'SELECT 1; DELETE FROM claims', 'SELECT * INTO copied FROM claims',
                    'SELECT * FROM incidents FOR UPDATE', 'SELECT * FROM claims FOR SHARE']:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                await q.execute(sql)
        self.assertEqual(raw.calls, [])
        self.assertEqual(q.queries, 0)

    async def test_parameterized_select_is_allowed(self):
        raw = ConnectionStub()
        q = SelectOnly(raw)
        self.assertEqual(await q.execute('SELECT id FROM incidents WHERE id=%s', ('fixture',)), 'read result')
        self.assertEqual(raw.calls, [('SELECT id FROM incidents WHERE id=%s', ('fixture',))])
        self.assertEqual(q.queries, 1)
