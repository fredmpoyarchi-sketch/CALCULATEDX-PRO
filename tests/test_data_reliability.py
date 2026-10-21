from contextlib import closing, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import data_admin
import database
from production import validate_database


class DataReliabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='calculatedx-data-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'active.sqlite3'
        data_admin.prepare(self.source, workers_stopped=True)
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.executemany('''INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, date_creation, visitor_id)
                VALUES (?, '+', ?, ?, '2026-10-21 12:34:56', ?)''',
                [(0.1, 0.2, 0.1 + 0.2, 'a' * 64),
                 (float(2 ** 63), 0.0, float(2 ** 63), 'b' * 64),
                 (99999.0, 1.0, 100000.0, None)])

    def manifest(self, path):
        return Path(str(path) + '.manifest.json')

    def rows(self, path):
        with closing(sqlite3.connect(path)) as connection:
            return connection.execute('SELECT * FROM calculs ORDER BY id').fetchall()

    def snapshot(self):
        path = self.root / 'backup.sqlite3'
        data_admin.backup(self.source, path)
        return path

    def test_backup_integrity_counts_and_binary64_values(self):
        before = self.source.read_bytes()
        snapshot = self.snapshot()
        result = data_admin.verify(snapshot, self.manifest(snapshot))
        self.assertEqual((result['rows'], result['legacy_rows'], result['schema_version']), (3, 1, 1))
        self.assertEqual(self.rows(snapshot), self.rows(self.source))
        self.assertEqual(self.rows(snapshot)[0][4].hex(), (0.1 + 0.2).hex())
        self.assertEqual(self.rows(snapshot)[1][4], float(2 ** 63))
        self.assertEqual(self.source.read_bytes(), before)
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchall(), [('ok',)])

    def test_snapshot_excludes_uncommitted_concurrent_write(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("INSERT INTO calculs (nombre1, operation, nombre2, resultat, visitor_id) VALUES (7, '+', 1, 8, 'a')")
            snapshot = self.snapshot()
            writer.rollback()
        self.assertEqual(len(self.rows(snapshot)), 3)
        self.assertEqual(data_admin.verify(snapshot, self.manifest(snapshot))['rows'], 3)

    def test_restore_is_a_new_verified_file_and_preserves_active_database(self):
        snapshot = self.snapshot()
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("INSERT INTO calculs (nombre1, operation, nombre2, resultat, visitor_id) VALUES (4, '*', 5, 20, 'a')")
        before = self.source.read_bytes()
        restored = self.root / 'restored.sqlite3'
        data_admin.restore(snapshot, self.manifest(snapshot), restored)
        self.assertEqual(self.rows(restored), self.rows(snapshot))
        self.assertEqual(restored.read_bytes(), snapshot.read_bytes())
        self.assertEqual(data_admin.verify(restored, self.manifest(restored))['rows'], 3)
        self.assertEqual(self.source.read_bytes(), before)
        with patch.object(database, 'DB_PATH', restored):
            self.assertEqual(len(database.lire_historique('a' * 64)), 1)
            self.assertEqual(len(database.lire_historique('b' * 64)), 1)
            self.assertEqual(database.lire_historique('stranger'), [])
            self.assertFalse(database.supprimer_calcul(1, 'b' * 64))
            self.assertEqual(database.obtenir_statistiques('a' * 64)['total'], 1)
        self.assertEqual(len(self.rows(restored)), 3)

    def test_legacy_migration_is_additive_and_idempotent(self):
        legacy = self.root / 'legacy.sqlite3'
        with closing(sqlite3.connect(legacy)) as connection, connection:
            connection.execute('''CREATE TABLE calculs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre1 REAL NOT NULL, operation TEXT NOT NULL, nombre2 REAL NOT NULL,
                resultat REAL NOT NULL, date_creation TEXT DEFAULT CURRENT_TIMESTAMP)''')
            connection.execute("INSERT INTO calculs VALUES (42, 0.1, '+', 0.2, ?, '2020-01-02 03:04:05')", (0.1 + 0.2,))
        legacy.chmod(0o600)
        before, rows = legacy.read_bytes(), self.rows(legacy)
        migrated = self.root / 'migrated.sqlite3'
        data_admin.prepare(migrated, source=legacy, workers_stopped=True)
        self.assertEqual(legacy.read_bytes(), before)
        self.assertEqual(self.rows(migrated), [(*rows[0], None)])
        with closing(sqlite3.connect(migrated)) as connection:
            for _ in range(2):
                with connection:
                    connection.execute('BEGIN IMMEDIATE')
                    database.appliquer_schema(connection)
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(sum(row[1] == 'visitor_id' for row in connection.execute('PRAGMA table_info(calculs)')), 1)
            self.assertEqual(sum(row[1] == 'idx_calculs_visitor_id' for row in connection.execute('PRAGMA index_list(calculs)')), 1)
        with patch.object(database, 'DB_PATH', migrated):
            self.assertEqual(database.lire_historique('a' * 64), [])
            database.enregistrer_calcul(2, '+', 3, 5, 'a' * 64)
            self.assertGreater(database.lire_historique('a' * 64)[0]['id'], 42)

    def test_preparation_requires_stopped_workers_and_does_not_overwrite(self):
        new = self.root / 'new.sqlite3'
        with self.assertRaises(ValueError):
            data_admin.prepare(new)
        self.assertFalse(new.exists())
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            data_admin.prepare(self.source, workers_stopped=True)
        self.assertEqual(self.source.read_bytes(), before)

    def test_future_schema_is_rejected_without_changing_source(self):
        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute('PRAGMA user_version = 99')
        before = self.source.read_bytes()
        target = self.root / 'future.sqlite3'
        with self.assertRaises(ValueError):
            data_admin.prepare(target, source=self.source, workers_stopped=True)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(target.exists())

    def test_unversioned_database_requires_preparation_before_worker(self):
        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute('PRAGMA user_version = 0')
        before = self.source.read_bytes()
        with self.assertRaises(ValueError):
            validate_database(self.source)
        self.assertEqual(self.source.read_bytes(), before)
        prepared = self.root / 'ready.sqlite3'
        data_admin.prepare(prepared, source=self.source, workers_stopped=True)
        validate_database(prepared)
        self.assertEqual(self.rows(prepared), self.rows(self.source))

    def test_cli_prepare_backup_verify_restore_roundtrip(self):
        prepared = self.root / 'cli-ready.sqlite3'
        snapshot = self.root / 'cli-snapshot.sqlite3'
        restored = self.root / 'cli-restored.sqlite3'
        commands = [
            ['prepare', '--source', str(self.source), '--destination', str(prepared), '--workers-stopped'],
            ['backup', '--source', str(prepared), '--destination', str(snapshot)],
            ['verify', '--snapshot', str(snapshot), '--manifest', str(self.manifest(snapshot))],
            ['restore', '--snapshot', str(snapshot), '--manifest', str(self.manifest(snapshot)),
             '--destination', str(restored)],
        ]
        for command in commands:
            with self.subTest(command=command[0]):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(data_admin.main(command), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result['state'], 'ok')
                self.assertEqual(result['rows'], 3)
        self.assertEqual(self.rows(restored), self.rows(self.source))

    def test_protected_paths_are_rejected_before_any_sqlite_access(self):
        forbidden = [Path(database.__file__).resolve().with_name('calculatedx.db'),
                     self.root / 'calculatedx.db', Path(database.__file__).resolve(),
                     Path('relative.sqlite3')]
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('Protected file must not be opened')):
            for path in forbidden:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    data_admin.backup(path, self.root / 'forbidden-copy.sqlite3')

    def test_existing_destinations_and_manifests_are_never_overwritten(self):
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            data_admin.backup(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), before)
        target = self.root / 'occupied.sqlite3'
        self.manifest(target).write_text('keep-existing-manifest', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            data_admin.backup(self.source, target)
        self.assertEqual(self.manifest(target).read_text(encoding='utf-8'), 'keep-existing-manifest')
        self.assertFalse(target.exists())

    def test_snapshot_tampering_is_rejected_before_restore(self):
        snapshot = self.snapshot()
        with snapshot.open('r+b') as stream:
            stream.write(b'BROKEN')
        target = self.root / 'bad-restore.sqlite3'
        with self.assertRaises(ValueError):
            data_admin.restore(snapshot, self.manifest(snapshot), target)
        self.assertFalse(target.exists())

    def test_snapshot_changed_after_verification_is_not_published(self):
        snapshot = self.snapshot()
        target = self.root / 'changed-restore.sqlite3'
        original_build = data_admin._build

        def change_then_build(*args, **kwargs):
            with closing(sqlite3.connect(snapshot)) as connection, connection:
                connection.execute("UPDATE calculs SET visitor_id = 'unexpected-owner'")
            return original_build(*args, **kwargs)

        with patch.object(data_admin, '_build', side_effect=change_then_build):
            with self.assertRaises(ValueError):
                data_admin.restore(snapshot, self.manifest(snapshot), target)
        self.assertFalse(target.exists())
        self.assertFalse(self.manifest(target).exists())
        self.assertEqual(len(self.rows(self.source)), 3)
        self.assertEqual(list(self.root.glob('.calculatedx-*')), [])

    def test_manifest_counts_and_corrupt_source_are_rejected(self):
        snapshot = self.snapshot()
        manifest = self.manifest(snapshot)
        values = json.loads(manifest.read_text(encoding='utf-8'))
        values['rows'] += 1
        manifest.write_text(json.dumps(values), encoding='utf-8')
        with self.assertRaises(ValueError):
            data_admin.verify(snapshot, manifest)
        broken = self.root / 'broken.sqlite3'
        broken.write_bytes(b'not-a-database')
        broken.chmod(0o600)
        target = self.root / 'no-output.sqlite3'
        with self.assertRaises(sqlite3.Error):
            data_admin.backup(broken, target)
        self.assertFalse(target.exists())

    def test_copy_timeout_leaves_source_intact_and_no_published_output(self):
        before = self.source.read_bytes()
        target = self.root / 'timeout.sqlite3'
        with patch.object(data_admin.time, 'monotonic', side_effect=[0.0, 99.0]):
            with self.assertRaises(TimeoutError):
                data_admin.backup(self.source, target)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(target.exists())
        self.assertFalse(self.manifest(target).exists())
        self.assertEqual(list(self.root.glob('.calculatedx-*')), [])

    def test_publication_race_cannot_overwrite_another_file(self):
        destination = self.root / 'race.sqlite3'
        real_link = os.link
        def racing_link(source, target):
            Path(target).write_bytes(b'existing-content')
            return real_link(source, target)
        with patch.object(data_admin.os, 'link', side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                data_admin.backup(self.source, destination)
        self.assertEqual(destination.read_bytes(), b'existing-content')

    def test_cli_failure_has_no_sensitive_diagnostic(self):
        output = StringIO()
        with patch.object(data_admin, 'backup', side_effect=OSError('SECRET-PATH')):
            with redirect_stdout(output):
                self.assertEqual(data_admin.main(['backup', '--source', '/unused', '--destination', '/other']), 1)
        self.assertEqual(json.loads(output.getvalue()), {'state': 'failed', 'operation': 'backup'})
        self.assertNotIn('SECRET-PATH', output.getvalue())

    def test_restored_wsgi_has_no_startup_migration_and_isolates_two_clients(self):
        snapshot = self.snapshot()
        restored = self.root / 'recovery.sqlite3'
        data_admin.restore(snapshot, self.manifest(snapshot), restored)
        script = '''
import os
from pathlib import Path
from unittest.mock import patch
import database
from production import Settings, create_application
with patch.object(database, 'appliquer_schema', side_effect=AssertionError('No schema writes in worker')):
    application = create_application(Settings.from_environment()).application
    first, second = application.test_client(), application.test_client()
    for client, owner in ((first, 'a' * 64), (second, 'b' * 64)):
        with client.session_transaction(base_url='https://calculator.test') as session:
            session['visitor_id'] = owner
        assert client.get('/historique', base_url='https://calculator.test').status_code == 200
        assert client.get('/api/v1/statistiques', base_url='https://calculator.test').json['total'] == 1
    with second.session_transaction(base_url='https://calculator.test') as session:
        token = session['csrf_token']
    assert second.post('/historique/supprimer/1', base_url='https://calculator.test',
                       headers={'X-CSRF-Token': token}).status_code == 404
    assert len(database.lire_historique('a' * 64)) == 1
print('ok')
'''
        environment = dict(os.environ, CALCULATEDX_SECRET_KEY='recovery-test-key-for-isolated-tests',
                           CALCULATEDX_DB_PATH=str(restored), CALCULATEDX_HOSTNAMES='calculator.test')
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(database.__file__).parent,
                                env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'ok')
        self.assertEqual(len(self.rows(restored)), 3)


if __name__ == '__main__':
    unittest.main()
