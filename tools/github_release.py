"""Explicit draft/upload/verify/publish for EYEPQC; Git credentials stay in memory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = '/repos/fantZach/EYEPQC'
TAG = 'v1.0.0'
TITLE = 'EYEPQC v1.0.0 - Development MVP'


class ReleaseError(RuntimeError):
    """Only static diagnostics; never echo HTTP bodies or credentials."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReleaseError('Unexpected HTTP redirect; credentials were not forwarded')


def credential():
    result = subprocess.run(
        ['git', '-c', 'credential.interactive=never', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\npath=fantZach/EYEPQC.git\n\n',
        capture_output=True, text=True, timeout=15,
        env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never',
                 GIT_ASKPASS='', SSH_ASKPASS=''),
    )
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    token = values.get('password', '')
    if result.returncode or not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ReleaseError('GitHub HTTPS credential unavailable; configure Git authentication locally')
    return token


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, path, payload=None, *, upload=False, missing=False):
        host = 'uploads.github.com' if upload else 'api.github.com'
        if not path.startswith(REPO + '/') and path != REPO:
            raise ReleaseError('Unexpected repository API path')
        data = payload if upload else (json.dumps(payload).encode() if payload is not None else None)
        request = urllib.request.Request('https://' + host + path, data=data, method=method, headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/octet-stream' if upload else 'application/json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'EYEPQC-release',
        })
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            raise ReleaseError(f'GitHub HTTP {error.code}; no automatic retry or overwrite') from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ReleaseError('GitHub transport/response failed; inspect remote state before retry') from None


def assets(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseError('Asset directory must be a real local directory')
    files = {}
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file() or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', path.name):
            raise ReleaseError('Asset directory must contain only explicitly prepared regular files')
        content = path.read_bytes()
        files[path.name] = (len(content), hashlib.sha256(content).hexdigest())
    sums = directory / 'SHA256SUMS.txt'
    if sums.name not in files:
        raise ReleaseError('SHA256SUMS.txt is required')
    declared = {}
    try:
        for line in sums.read_text(encoding='ascii').splitlines():
            match = re.fullmatch(r'([0-9a-fA-F]{64})  ([A-Za-z0-9][A-Za-z0-9._-]{0,127})', line)
            if not match or match[2] in declared:
                raise ReleaseError('Invalid or duplicate checksum entry')
            declared[match[2]] = match[1].lower()
    except UnicodeError:
        raise ReleaseError('Checksum manifest must be ASCII') from None
    expected = {name: digest for name, (_, digest) in files.items() if name != sums.name}
    if not expected or declared != expected:
        raise ReleaseError('Checksum manifest does not match the complete asset directory')
    return files


def verify_assets(release, files):
    uploaded = release.get('assets', [])
    if len(uploaded) != len(files) or {asset.get('name') for asset in uploaded} != set(files):
        raise ReleaseError('Remote asset set differs; leave draft unpublished')
    for asset in uploaded:
        size, digest = files[asset['name']]
        if asset.get('state') != 'uploaded' or asset.get('size') != size or asset.get('digest') != 'sha256:' + digest:
            raise ReleaseError('Remote asset size/digest mismatch; leave draft unpublished')


def release_tag(value):
    if not isinstance(value, str) or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?', value):
        raise ReleaseError('Use an explicit version tag such as v1.1.0')
    return value


def verify_tag(api, commit, tag=TAG):
    tag = release_tag(tag)
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ReleaseError('Target commit must be a full lowercase SHA-1')
    ref = api.request('GET', REPO + '/git/ref/tags/' + tag)
    obj = ref['object']
    if obj['type'] == 'tag':
        obj = api.request('GET', REPO + '/git/tags/' + obj['sha'])['object']
    if obj.get('type') != 'commit' or obj.get('sha') != commit:
        raise ReleaseError('Remote release tag does not resolve to the reviewed commit')


def run(args, api):
    tag = release_tag(getattr(args, 'tag', TAG))
    title = getattr(args, 'title', None)
    if title is None:
        title = TITLE if tag == TAG else 'EYEPQC ' + tag
    if not isinstance(title, str) or not title.strip() or len(title) > 200 or any(ord(c) < 32 for c in title):
        raise ReleaseError('Release title must be nonempty single-line text, at most 200 characters')
    if args.mode == 'inspect':
        repo = api.request('GET', REPO)
        releases = api.request('GET', REPO + '/releases?per_page=100')
        return {'repository': repo['full_name'], 'private': repo['private'], 'requested_tag': tag,
                'permissions': repo.get('permissions', {}), 'releases': [
                    {key: release.get(key) for key in ('id', 'tag_name', 'draft', 'html_url')}
                    for release in releases]}
    if not args.assets or not args.commit:
        raise ReleaseError('Draft/publish require --assets and --commit')
    files = assets(args.assets)
    verify_tag(api, args.commit, tag)
    if args.mode == 'draft':
        if not args.notes:
            raise ReleaseError('Draft requires --notes')
        # Listing includes drafts for authenticated push users; do not recreate an interrupted draft.
        releases = api.request('GET', REPO + '/releases?per_page=100')
        if any(release.get('tag_name') == tag for release in releases):
            raise ReleaseError('Release already exists; inspect it, never overwrite automatically')
        if len(releases) >= 100:
            raise ReleaseError('Release list may be truncated; inspect remote state before creating a draft')
        body = Path(args.notes).read_text(encoding='utf-8')
        release = api.request('POST', REPO + '/releases', {
            'tag_name': tag, 'target_commitish': args.commit,
            'name': title, 'body': body,
            'draft': True, 'prerelease': False,
        })
        if release.get('tag_name') != tag or release.get('draft') is not True:
            raise ReleaseError('Created draft identity unconfirmed; inspect remote state before uploading')
        release_id = release['id']
        if type(release_id) is not int or release_id < 1:
            raise ReleaseError('Created draft id invalid; inspect remote state before uploading')
        # An interrupted upload leaves its draft intact for manual inspection, not delete/retry.
        for name, (_, digest) in files.items():
            content = (Path(args.assets) / name).read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ReleaseError('Local asset changed after preflight; leave draft unpublished')
            api.request('POST', REPO + f'/releases/{release_id}/assets?name=' + urllib.parse.quote(name), content, upload=True)
        release = api.request('GET', REPO + f'/releases/{release_id}')
        verify_assets(release, files)
    else:
        if not args.release_id or args.release_id < 1:
            raise ReleaseError('Publish requires the inspected --release-id')
        release_id = args.release_id
        release = api.request('GET', REPO + f'/releases/{release_id}')
        if release.get('tag_name') != tag or release.get('draft') is not True:
            raise ReleaseError('Release is not the expected unpublished draft')
        verify_assets(release, files)
        release = api.request('PATCH', REPO + f'/releases/{release_id}', {'draft': False})
        if release.get('draft') is not False or release.get('tag_name') != tag:
            raise ReleaseError('Publish status unconfirmed; inspect remote state')
    return {key: release.get(key) for key in ('id', 'tag_name', 'draft', 'html_url')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('inspect', 'draft', 'publish'), default='inspect')
    parser.add_argument('--assets')
    parser.add_argument('--notes')
    parser.add_argument('--commit')
    parser.add_argument('--release-id', type=int)
    parser.add_argument('--tag', default=TAG, help='Reviewed existing version tag; defaults to v1.0.0')
    parser.add_argument('--title', help='Draft title; defaults to the version label (legacy title for v1.0.0)')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args, GitHub(credential())), ensure_ascii=False, indent=2))
        return 0
    except ReleaseError as error:
        print('RELEASE_ERROR: ' + str(error), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
        # Never print unexpected library/subprocess details, which can contain authentication material.
        print('RELEASE_ERROR: preflight/API operation failed; no automatic retry, overwrite or deletion', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
