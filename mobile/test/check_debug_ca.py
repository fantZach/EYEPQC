"""Check source and built APK isolation against the independently supplied public CA fingerprint."""
import hashlib
from pathlib import Path
import re
import ssl
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile


def check(root, aapt, fingerprint):
    app = root / 'mobile/app'
    source = app / 'src'
    pem = (source / 'debug/res/raw/eyepqc_test_ca.pem').read_bytes()
    assert pem.count(b'-----BEGIN CERTIFICATE-----') == 1
    assert pem.strip().startswith(b'-----BEGIN CERTIFICATE-----') and pem.strip().endswith(b'-----END CERTIFICATE-----')
    der = ssl.PEM_cert_to_DER_cert(pem.decode('ascii'))
    assert hashlib.sha256(der).hexdigest() == fingerprint.lower().replace(':', '')
    for path in source.rglob('*'):
        if path.is_file():
            content = path.read_bytes()
            assert not re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----', content), path
            if 'debug' not in path.relative_to(source).parts:
                assert b'eyepqc_test_ca' not in content and b'eyepqc_debug_network_security' not in content, path
                assert pem not in content and der not in content, path
    android = '{http://schemas.android.com/apk/res/android}'
    manifest = ET.parse(source / 'debug/AndroidManifest.xml').getroot().find('application')
    assert manifest.get(android + 'networkSecurityConfig') == '@xml/eyepqc_debug_network_security'
    config = ET.parse(source / 'debug/res/xml/eyepqc_debug_network_security.xml').getroot()
    assert [c.get('src') for c in config.findall('./base-config/trust-anchors/certificates')] == ['system']
    anchors = config.findall('./debug-overrides/trust-anchors/certificates')
    assert len(anchors) == 1 and anchors[0].attrib == {'src': '@raw/eyepqc_test_ca', 'overridePins': 'false'}
    assert len(config.findall('.//certificates')) == 2
    for variant, filename in [('debug', 'app-debug.apk'), ('release', 'app-release-unsigned.apk')]:
        apk = app / 'build/outputs/apk' / variant / filename
        tree = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'], text=True)
        with zipfile.ZipFile(apk) as archive:
            names = archive.namelist()
            if variant == 'debug':
                assert archive.read('res/raw/eyepqc_test_ca.pem') == pem
                assert 'android:networkSecurityConfig' in tree
                assert re.search(r'android:debuggable[^\n]*0xffffffff', tree)
                xml = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), 'res/xml/eyepqc_debug_network_security.xml'], text=True)
                assert 'debug-overrides' in xml and 'overridePins' in xml
                assert re.search(r'overridePins[^\n]*(?:0x0|"false")', xml)
            else:
                assert not any('eyepqc_test_ca' in n or 'eyepqc_debug_network_security' in n for n in names)
                assert 'android:networkSecurityConfig' not in tree
                assert not re.search(r'android:debuggable[^\n]*0xffffffff', tree)
                for name in names:
                    content = archive.read(name)
                    assert pem not in content and der not in content, name
            for name in names:
                assert not re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----', archive.read(name)), name
        print('DEBUG_CA_ISOLATION_OK variant=' + variant)
    print('CA_SHA256=' + hashlib.sha256(der).hexdigest())


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Usage: check_debug_ca.py <repo> <aapt> <public CA SHA256 fingerprint>')
    check(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
