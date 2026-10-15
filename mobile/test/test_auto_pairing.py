"""Real JVM/HTTPS fetch, isolated public fixtures only; no board or deployed service."""
import base64
import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get('JAVA_HOME', 'C:/Users/23976/AppData/Local/Programs/STM32CubeMX/jre'))/'bin/java.exe'
TOOLS = ROOT/'build/mobile_toolchain'
CLASSPATH = os.pathsep.join(str(TOOLS/name) for name in ('classes','bcprov.jar','okhttp.jar','okio.jar','kotlin.jar','gson.jar'))


def run():
    with tempfile.TemporaryDirectory(prefix='eyepqc-auto-pairing-') as temporary:
        folder = Path(temporary)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
                .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False).sign(key,hashes.SHA256()))
        public, private, store = folder/'cert.pem', folder/'key.pem', folder/'trust.p12'
        public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        subprocess.run([str(JAVA.with_name('keytool.exe')),'-importcert','-noprompt','-alias','fixture','-file',str(public),
                        '-keystore',str(store),'-storetype','PKCS12','-storepass','public-only'],check=True,capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(public,private)
        for scenario in ('success','wrong_password','redirect','cross_origin','downgrade','identity_changed','oversize','unbounded_oversize','untrusted_ca','wrong_hostname'):
            requests = []
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_GET(self):
                    requests.append(self.path)
                    expected = 'Basic '+base64.b64encode(b'public-fixture-user:public-fixture-password').decode()
                    assert self.headers.get('Authorization') == expected
                    config = dict(version=2,endpoint=f'wss://localhost:{self.server.server_port}/stream',
                                  public_key_hex=bytes(800).hex(),public_key_sha256=hashlib.sha256(bytes(800)).hexdigest())
                    if scenario=='cross_origin': config['endpoint']='wss://other.example/stream'
                    if scenario=='downgrade': config.update(version=1,token='x'*32)
                    body = b' '*8193 if 'oversize' in scenario else json.dumps(config).encode()
                    self.send_response(401 if scenario=='wrong_password' else 302 if scenario=='redirect' else 200)
                    if scenario=='redirect': self.send_header('Location','https://other.example/pairing.json')
                    if scenario!='unbounded_oversize': self.send_header('Content-Length',str(len(body)))
                    self.send_header('Connection','close')
                    self.end_headers()
                    try: self.wfile.write(body)
                    except (BrokenPipeError,ConnectionResetError,ssl.SSLError): pass
            server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
            server.socket = context.wrap_socket(server.socket,server_side=True)
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            options = [] if scenario=='untrusted_ca' else ['-Djavax.net.ssl.trustStore='+str(store),'-Djavax.net.ssl.trustStorePassword=public-only']
            host = '127.0.0.1' if scenario=='wrong_hostname' else 'localhost'
            expected = 'success' if scenario=='success' else 'failure'
            pin = 'ff'*32 if scenario=='identity_changed' else '-'
            try:
                result = subprocess.run([str(JAVA),*options,'-cp',CLASSPATH,'org.eyepqc.mobile.PairingFetchCli',
                                         f'wss://{host}:{server.server_port}/stream',expected,pin],capture_output=True,timeout=25)
                assert result.returncode==0, result.stderr.decode(errors='replace')
                assert b'PAIRING_FETCH_OK' in result.stdout
                assert requests == ([] if scenario in ('untrusted_ca','wrong_hostname') else ['/pairing.json']), requests
                print('AUTO_PAIRING_HTTPS_OK',scenario)
            finally:
                server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__': run()
