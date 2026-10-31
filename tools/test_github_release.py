"""Offline release guard checks; no Git credential helper or network calls."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import github_release as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'app.zip').write_bytes(b'fixture archive')
        self.sums()

    def sums(self):
        digest = hashlib.sha256((self.root / 'app.zip').read_bytes()).hexdigest()
        (self.root / 'SHA256SUMS.txt').write_text(digest + '  app.zip\n', encoding='ascii')

    def test_manifest_requires_complete_matching_asset_set(self):
        self.assertEqual(set(release.assets(self.root)), {'app.zip', 'SHA256SUMS.txt'})
        (self.root / 'unexpected.pem').write_text('unreviewed')
        with self.assertRaises(release.ReleaseError):
            release.assets(self.root)
        (self.root / 'unexpected.pem').unlink()
        (self.root / 'app.zip').write_bytes(b'changed')
        with self.assertRaises(release.ReleaseError):
            release.assets(self.root)

    def test_duplicate_checksum_or_subdirectory_rejected(self):
        sums = self.root / 'SHA256SUMS.txt'
        sums.write_text(sums.read_text() * 2)
        with self.assertRaises(release.ReleaseError):
            release.assets(self.root)
        self.sums()
        (self.root / 'private').mkdir()
        with self.assertRaises(release.ReleaseError):
            release.assets(self.root)

    def test_remote_size_hash_and_name_must_all_match(self):
        files = release.assets(self.root)
        remote = {'assets': [{'name': name, 'size': size, 'digest': 'sha256:' + digest, 'state': 'uploaded'}
                             for name, (size, digest) in files.items()]}
        release.verify_assets(remote, files)
        remote['assets'][0]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaises(release.ReleaseError):
            release.verify_assets(remote, files)
        remote['assets'].pop()
        with self.assertRaises(release.ReleaseError):
            release.verify_assets(remote, files)

    def test_lightweight_and_annotated_tags(self):
        class API:
            def request(self, method, path):
                if '/git/ref/' in path:
                    return {'object': {'type': 'tag', 'sha': 'b' * 40}}
                return {'object': {'type': 'commit', 'sha': 'a' * 40}}
        release.verify_tag(API(), 'a' * 40)
        with self.assertRaises(release.ReleaseError):
            release.verify_tag(API(), 'c' * 40)
        with self.assertRaises(release.ReleaseError):
            release.verify_tag(API(), 'main')

    def test_draft_upload_then_explicit_publish(self):
        files = release.assets(self.root)
        calls = []
        state = {'id': 123, 'tag_name': release.TAG, 'draft': True, 'assets': [],
                 'html_url': 'https://github.com/fantZach/EYEPQC/releases/tag/v1.0.0'}
        class API:
            def request(self, method, path, payload=None, **kwargs):
                calls.append((method, path))
                if '/git/ref/' in path:
                    return {'object': {'type': 'commit', 'sha': 'a' * 40}}
                if path.endswith('releases?per_page=100'):
                    return []
                if kwargs.get('upload'):
                    name = path.split('?name=')[1]
                    state['assets'].append({'name': name, 'size': len(payload), 'state': 'uploaded',
                                            'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()})
                if method == 'PATCH':
                    state['draft'] = payload['draft']
                return state
        notes = self.root.parent / (self.root.name + '-notes.md')
        notes.write_text('Release fixture', encoding='utf-8')
        self.addCleanup(notes.unlink)
        args = argparse.Namespace(mode='draft', assets=self.root, notes=notes, commit='a' * 40, release_id=None)
        self.assertTrue(release.run(args, API())['draft'])
        self.assertFalse(any(method == 'PATCH' for method, _ in calls))
        self.assertEqual(len(state['assets']), len(files))
        args.mode = 'publish'
        args.release_id = 123
        self.assertFalse(release.run(args, API())['draft'])
        self.assertEqual(sum(method == 'PATCH' for method, _ in calls), 1)

    def test_existing_release_not_overwritten(self):
        class API:
            def request(self, method, path, *args, **kwargs):
                if '/git/ref/' in path:
                    return {'object': {'type': 'commit', 'sha': 'a' * 40}}
                if method != 'GET':
                    raise AssertionError('must not mutate')
                return [{'tag_name': release.TAG}]
        args = argparse.Namespace(mode='draft', assets=self.root, notes='unused', commit='a' * 40)
        with self.assertRaises(release.ReleaseError):
            release.run(args, API())

    def test_explicit_tag_title_creates_only_new_draft_and_checks_new_ref(self):
        calls = []
        state = {'id': 456, 'tag_name': 'v1.1.0', 'draft': True, 'assets': []}
        class API:
            def request(self, method, path, payload=None, **kwargs):
                calls.append((method, path, payload))
                if '/git/ref/' in path:
                    self_test.assertTrue(path.endswith('/tags/v1.1.0'))
                    return {'object': {'type': 'commit', 'sha': 'a' * 40}}
                if path.endswith('releases?per_page=100'):
                    return [{'tag_name': 'v1.0.0', 'draft': False}]
                if kwargs.get('upload'):
                    state['assets'].append({'name': path.split('?name=')[1], 'size': len(payload),
                                            'state': 'uploaded',
                                            'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()})
                return state
        self_test = self
        notes = self.root.parent / (self.root.name + '-new-notes.md')
        notes.write_text('New release fixture', encoding='utf-8')
        self.addCleanup(notes.unlink)
        args = argparse.Namespace(mode='draft', assets=self.root, notes=notes, commit='a' * 40,
                                  release_id=None, tag='v1.1.0', title='EYEPQC 1.1.0')
        self.assertTrue(release.run(args, API())['draft'])
        creates = [payload for method, path, payload in calls if method == 'POST' and path.endswith('/releases')]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]['tag_name'], 'v1.1.0')
        self.assertEqual(creates[0]['name'], 'EYEPQC 1.1.0')
        self.assertFalse(any(method in ('PATCH', 'DELETE') for method, _, _ in calls))

    def test_invalid_tag_or_title_rejected_before_api_access(self):
        class API:
            def request(self, *args, **kwargs):
                raise AssertionError('must not contact API')
        for tag, title in [('v1.1.0/../v1.0.0', 'Title'), ('main', 'Title'),
                           ('v1.1.0', ''), ('v1.1.0', 'bad\nname')]:
            with self.subTest(tag=tag, title=title), self.assertRaises(release.ReleaseError):
                release.run(argparse.Namespace(mode='inspect', tag=tag, title=title), API())

    def test_publish_wrong_id_tag_or_published_release_never_patches(self):
        files = release.assets(self.root)
        for tag, draft in [('v1.0.0', True), ('v1.1.0', False)]:
            class API:
                def request(self, method, path, *args, **kwargs):
                    if method != 'GET':
                        raise AssertionError('must not mutate')
                    if '/git/ref/' in path:
                        return {'object': {'type': 'commit', 'sha': 'a' * 40}}
                    return {'id': 123, 'tag_name': tag, 'draft': draft, 'assets': [
                        {'name': name, 'size': size, 'state': 'uploaded', 'digest': 'sha256:' + digest}
                        for name, (size, digest) in files.items()]}
            args = argparse.Namespace(mode='publish', assets=self.root, commit='a' * 40,
                                      release_id=123, tag='v1.1.0', title=None)
            with self.subTest(tag=tag, draft=draft), self.assertRaises(release.ReleaseError):
                release.run(args, API())

    def test_remote_incomplete_upload_or_wrong_size_rejected(self):
        files = release.assets(self.root)
        for field, value in [('state', 'starter'), ('size', -1), ('digest', None)]:
            remote = {'assets': [{'name': name, 'size': size, 'digest': 'sha256:' + digest, 'state': 'uploaded'}
                                 for name, (size, digest) in files.items()]}
            remote['assets'][0][field] = value
            with self.subTest(field=field), self.assertRaises(release.ReleaseError):
                release.verify_assets(remote, files)

    def test_credentials_captured_not_logged_or_prompted(self):
        result = argparse.Namespace(stdout='username=fixture\npassword=fixture-not-real\n', returncode=0)
        with patch.object(release.subprocess, 'run', return_value=result) as run:
            self.assertEqual(release.credential(), 'fixture-not-real')
            self.assertTrue(run.call_args.kwargs['capture_output'])
            self.assertEqual(run.call_args.kwargs['env']['GIT_TERMINAL_PROMPT'], '0')
        result.stdout = 'password=bad\x01token\n'
        with patch.object(release.subprocess, 'run', return_value=result), self.assertRaises(release.ReleaseError):
            release.credential()

    def test_bearer_never_forwarded_on_redirect(self):
        with self.assertRaises(release.ReleaseError):
            release.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid')


if __name__ == '__main__':
    unittest.main()
