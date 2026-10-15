import argparse, base64, getpass, hashlib, hmac, json, os, secrets, time
from contextlib import contextmanager
from pathlib import Path
import tempfile

MAX_FILE_BYTES = 64 * 1024


def valid_username(username):
    return (isinstance(username, str) and bool(username) and ':' not in username
            and len(username.encode('utf-8')) <= 128
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in username))


def validate_users(users):
    if not isinstance(users, dict) or not 1 <= len(users) <= 100:
        raise ValueError('invalid accounts file')
    for name, item in users.items():
        if (not valid_username(name) or not isinstance(item, dict) or set(item) != {'salt', 'hash'}
                or any(not isinstance(item[field], str) for field in ('salt', 'hash'))
                or len(item['salt']) != 32 or len(item['hash']) != 64
                or len(bytes.fromhex(item['salt'])) != 16 or len(bytes.fromhex(item['hash'])) != 32):
            raise ValueError('invalid accounts file')
    return users


def read_users(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate accounts field')
            result[key] = value
        return result
    with Path(path).open('rb') as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('accounts file too large')
    return validate_users(json.loads(raw.decode('utf-8'), object_pairs_hook=unique))


@contextmanager
def account_lock(path):
    # Keep the sidecar inode: deleting it could allow two writers to lock different files.
    descriptor = os.open(str(path) + '.lock', os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b'\0')
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise RuntimeError('account file is busy; retry after the other command finishes') from None
        yield
    finally:
        try:
            if locked:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def write_users(path, users, *, exclusive=False):
    validate_users(users)
    data = (json.dumps(users, ensure_ascii=False) + '\n').encode('utf-8')
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('accounts file too large')
    descriptor, temporary = tempfile.mkstemp(prefix='.accounts-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as destination:
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())
        if exclusive:
            if os.name == 'nt':
                os.rename(temporary, path)  # Windows rename refuses an existing destination.
            else:
                os.link(temporary, path)  # Atomic no-replace publication on POSIX.
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def password_record(username, password):
    if (not valid_username(username) or not isinstance(password, str) or not password or len(password.encode('utf-8')) > 1024
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in password)):
        raise ValueError('invalid username or password')
    salt = secrets.token_bytes(16)
    return dict(salt=salt.hex(), hash=password_hash(password, salt).hex())


def password_hash(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=131072, r=8, p=1, dklen=32, maxmem=256 * 1024 * 1024)


def create_account(path, username, password):
    path = Path(path)
    with account_lock(path):
        if path.exists():
            raise FileExistsError('account file exists')
        write_users(path, {username: password_record(username, password)}, exclusive=True)


def change_account(path, action, username, password=None, *, confirmed=False):
    path = Path(path)
    if action not in ('add', 'passwd', 'delete') or not valid_username(username):
        raise ValueError('invalid account operation')
    with account_lock(path):
        existed = path.exists()
        users = read_users(path) if existed else {}
        if action == 'add':
            if username in users or len(users) >= 100:
                raise ValueError('user already exists or account limit reached')
            users[username] = password_record(username, password)
        elif action == 'passwd':
            if username not in users:
                raise ValueError('user does not exist')
            users[username] = password_record(username, password)
        else:
            if not confirmed or username not in users or len(users) <= 1:
                raise ValueError('delete requires confirmation, existing user and at least one remaining account')
            del users[username]
        write_users(path, users, exclusive=not existed)


class Accounts:
    def __init__(self, path):
        self.users = read_users(path)
        self.allowance = 5.0
        self.updated = time.monotonic()

    # shortcut: global single-process limiter, replace when multiple relay processes are deployed.
    def admit(self):
        now = time.monotonic()
        self.allowance = min(5.0, self.allowance + now - self.updated)
        self.updated = now
        if self.allowance < 1:
            return False
        self.allowance -= 1
        return True

    def verify(self, header):
        try:
            if not header.startswith('Basic ') or len(header) > 1800:
                return None
            value = base64.b64decode(header[6:], validate=True).decode('utf-8')
            username, password = value.split(':', 1)
            if not username or len(username.encode('utf-8')) > 128 or len(password.encode('utf-8')) > 1024:
                return None
            item = self.users.get(username)
            salt = bytes.fromhex(item['salt']) if item else bytes(16)
            expected = bytes.fromhex(item['hash']) if item else bytes(32)
            valid = hmac.compare_digest(password_hash(password, salt), expected)
            return username if valid and item else None
        except (ValueError, UnicodeError):
            return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create private salted-scrypt account file; refuses overwrite')
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--username', required=True)
    args = parser.parse_args()
    password = getpass.getpass('Password: ')
    if password != getpass.getpass('Repeat password: '):
        parser.error('passwords differ')
    create_account(args.file, args.username, password)
    print('Account file created')
