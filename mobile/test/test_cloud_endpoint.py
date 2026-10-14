"""Isolated synthetic TLS listener; no deployed relay, cloud, SSH, credentials or hardware."""
import datetime
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get('JAVA_HOME', 'C:/Users/23976/AppData/Local/Programs/STM32CubeMX/jre')) / 'bin/java.exe'
TOOLS = ROOT / 'build/mobile_toolchain'
CLASSPATH = os.pathsep.join(str(TOOLS / name) for name in ('classes', 'bcprov.jar', 'okhttp.jar', 'okio.jar', 'kotlin.jar'))


def run():
    with tempfile.TemporaryDirectory(prefix='eyepqc-cloud-tls-') as folder:
        folder = Path(folder)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'public-cloud-fixture')])
        now = datetime.datetime.now(datetime.timezone.utc)
        for host, trusted, status, takeover in [('localhost', False, 0, False), ('wrong.example', True, 0, False), ('localhost', True, 409, False), ('localhost', True, 503, True)]:
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
                    .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False).sign(key, hashes.SHA256()))
            public, private, store = folder/'fixture.pem', folder/'fixture.key', folder/'trust.p12'
            public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            if store.exists():
                store.unlink()
            subprocess.run([str(JAVA.with_name('keytool.exe')), '-importcert', '-noprompt', '-alias', 'fixture', '-file', str(public), '-keystore', str(store), '-storetype', 'PKCS12', '-storepass', 'public-fixture-password'], check=True, capture_output=True)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(public, private)
            requests, errors = [], []
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0));listener.listen();listener.settimeout(10)
                port = listener.getsockname()[1]
                def serve():
                    try:
                        with listener.accept()[0] as connection:
                            connection.settimeout(5)
                            try:
                                with context.wrap_socket(connection, server_side=True) as tls:
                                    data = b''
                                    while b'\r\n\r\n' not in data:
                                        part = tls.recv(4096)
                                        if not part: break
                                        data += part
                                    if data:
                                        requests.append(data.split(b'\r\n', 1)[0])
                                        tls.sendall(f'HTTP/1.1 {status} Fixture\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode())
                            except ssl.SSLError:
                                if status: raise
                    except Exception as error:
                        errors.append(type(error).__name__)
                thread = threading.Thread(target=serve)
                thread.start()
                options = ['-Djavax.net.ssl.trustStore='+str(store), '-Djavax.net.ssl.trustStorePassword=public-fixture-password'] if trusted else []
                expected = '服务拒绝连接 HTTP '+str(status) if status else '连接失败'
                try:
                    result = subprocess.run([str(JAVA), *options, '-cp', CLASSPATH, 'org.eyepqc.mobile.CloudEndpointCli', f'wss://localhost:{port}/stream', expected, str(takeover).lower()], capture_output=True, timeout=15)
                    assert result.returncode == 0, result.stderr.decode(errors='replace')
                    assert b'CLOUD_ENDPOINT_OK' in result.stdout
                finally:
                    thread.join(10)
                assert not thread.is_alive() and not errors, errors
                expected_requests = [] if not status else [b'GET /stream?takeover=1 HTTP/1.1' if takeover else b'GET /stream HTTP/1.1']
                assert requests == expected_requests
                print(f'CLOUD_TLS_OK trusted={trusted} SAN={host} status={status} explicit_takeover={takeover}')


if __name__ == '__main__':
    run()
