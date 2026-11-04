import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jt.tools import Tool, problem  # noqa: E402


def tool(**kw):
    return Tool('x', 'X', build=lambda parent, app: None, **kw)


class ProblemTests(unittest.TestCase):
    def test_a_tool_without_requirements_is_on(self):
        self.assertEqual(problem(tool(), lambda name: False), '')

    def test_missing_tables_are_named(self):
        have = {'FW_TABLES'}
        self.assertEqual(problem(tool(requires=('FW_TABLES',)), have.__contains__), '')
        self.assertEqual(problem(tool(requires=('FW_TABLES', 'FW_TABLE_FIELDS')), have.__contains__),
                         'needs FW_TABLE_FIELDS: not found on this database')
        self.assertEqual(problem(tool(requires=('A', 'B')), lambda name: False),
                         'needs A, B: not found on this database')

    def test_a_custom_check_gives_its_own_reason(self):
        self.assertEqual(problem(tool(check=lambda app: 'because'), lambda name: True), 'because')
        self.assertEqual(problem(tool(check=lambda app: ''), lambda name: True), '')
        self.assertEqual(problem(tool(check=lambda app: None), lambda name: True), '')

    def test_the_tables_are_checked_before_the_custom_check(self):
        called = []
        t = tool(requires=('A',), check=lambda app: called.append(1) or 'custom')
        self.assertTrue(problem(t, lambda name: False).startswith('needs A'))
        self.assertEqual(called, [])

    def test_the_check_gets_what_the_caller_passes(self):
        seen = []
        problem(tool(check=lambda app: seen.append(app) or ''), lambda name: True, extra='the-app')
        self.assertEqual(seen, ['the-app'])


if __name__ == '__main__':
    unittest.main()
