from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
from collections import namedtuple
import tempfile
import unittest
from unittest.mock import patch

import monitor


class StorageMonitorTests(unittest.TestCase):
    def test_disk_thresholds_without_filling_disk_or_opening_sqlite(self):
        usage = namedtuple('Usage', 'total used free')
        with tempfile.TemporaryDirectory(prefix='calculatedx-monitor-') as temporary:
            path = Path(temporary) / 'test.db'
            path.write_bytes(b'not opened as SQLite')
            before = path.read_bytes()
            for free, fraction, expected in ((2048, 0.1, 'ok'), (1023, 0.1, 'critical'),
                                              (2048, 0.5, 'critical')):
                with self.subTest(free=free, fraction=fraction):
                    with patch.object(monitor.shutil, 'disk_usage', return_value=usage(8192, 8192-free, free)):
                        result = monitor.check_storage(path, min_free_bytes=1024,
                                                       min_free_fraction=fraction)
                    self.assertEqual(result['state'], expected)
                    self.assertNotIn(str(path), json.dumps(result))
            self.assertEqual(path.read_bytes(), before)

    def test_exit_codes_and_safe_unknown_diagnostic(self):
        for state, code in (('ok', 0), ('critical', 2)):
            output = StringIO()
            with patch.object(monitor, 'check_storage', return_value={'state': state}):
                with redirect_stdout(output):
                    self.assertEqual(monitor.main(), code)
            self.assertEqual(json.loads(output.getvalue())['state'], state)
        output = StringIO()
        with patch.object(monitor, 'check_storage', side_effect=OSError('SECRET-PATH')):
            with redirect_stdout(output):
                self.assertEqual(monitor.main(), 2)
        self.assertEqual(json.loads(output.getvalue()), {'check': 'sqlite_volume', 'state': 'unknown'})
        self.assertNotIn('SECRET-PATH', output.getvalue())

    def test_missing_path_does_not_create_file(self):
        with tempfile.TemporaryDirectory(prefix='calculatedx-monitor-') as temporary:
            path = Path(temporary) / 'absent.db'
            with patch.dict(os.environ, CALCULATEDX_DB_PATH=str(path)):
                with redirect_stdout(StringIO()):
                    self.assertEqual(monitor.main(), 2)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
