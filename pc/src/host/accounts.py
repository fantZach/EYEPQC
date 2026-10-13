import argparse, base64, getpass, hashlib, hmac, json, os, secrets, time
from pathlib import Path


def password_hash(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=131072, r=8, p=1, dklen=32, maxmem=256 * 1024 * 1024)


def create_account(path, username, password):
    if not username or ':' in username or len(username.encode('utf-8')) > 128 or any(ord(c) < 32 for c in username):
        raise ValueError('invalid username')
    if not password or len(password.encode('utf-8')) > 1024:
        raise ValueError('invalid password length')
    salt = secrets.token_bytes(16)
    record = {username: dict(salt=salt.hex(), hash=password_hash(password, salt).hex())}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(record, f)


class Accounts:
    def __init__(self, path):
        self.users = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(self.users, dict) or not self.users or len(self.users) > 100:
            raise ValueError('invalid accounts file')
        for name, item in self.users.items():
            if (not isinstance(name, str) or not name or ':' in name or len(name.encode('utf-8')) > 128
                    or any(ord(c) < 32 for c in name) or not isinstance(item, dict)
                    or set(item) != {'salt', 'hash'}
                    or len(bytes.fromhex(item['salt'])) != 16 or len(bytes.fromhex(item['hash'])) != 32):
                raise ValueError('invalid accounts file')
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
