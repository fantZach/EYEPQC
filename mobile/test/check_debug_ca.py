"""Check both APK variants trust only system roots or one explicitly supplied public CA."""
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile


def check(root, aapt, deployment_ca=None):
    app = root / 'mobile/app'
    source = app / 'src'
    deployment = Path(deployment_ca).read_bytes() if deployment_ca else None
    assert not (source / 'debug/res/raw/eyepqc_test_ca.pem').exists()
    config = ET.parse(source / 'debug/res/xml/eyepqc_debug_network_security.xml').getroot()
    assert [c.get('src') for c in config.findall('.//certificates')] == ['system']
    assert config.find('./base-config').get('cleartextTrafficPermitted') == 'false'
    for path in source.rglob('*'):
        if path.is_file():
            assert not re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----', path.read_bytes()), path
    for variant, filename in [('debug', 'app-debug.apk'), ('release', 'app-release-unsigned.apk')]:
        apk = app / 'build/outputs/apk' / variant / filename
        tree = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'], text=True)
        resources = subprocess.check_output([str(aapt), 'dump', '--values', 'resources', str(apk)], text=True)

        def resource_path(name):
            match = re.search(r'resource \S+ org\.eyepqc\.mobile:'+re.escape(name)+r':[^\n]*\n\s*\(string8\) "([^"]+)"', resources)
            assert match, name
            return match[1]

        with zipfile.ZipFile(apk) as archive:
            assert not any('eyepqc_test_ca' in name for name in archive.namelist())
            assert 'eyepqc_test_ca' not in resources
            if deployment:
                assert archive.read(resource_path('raw/eyepqc_deployment_ca')) == deployment
                xml = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), resource_path('xml/eyepqc_deployment_network_security')], text=True)
                assert 'debug-overrides' not in xml
                assert re.search(r'overridePins[^\n]*(?:0x0|"false")', xml)
                assert re.search(r'cleartextTrafficPermitted[^\n]*(?:0x0|"false")', xml)
            else:
                assert 'eyepqc_deployment_ca' not in resources
                if variant == 'release':
                    assert 'android:networkSecurityConfig' not in tree
                else:
                    xml = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), resource_path('xml/eyepqc_debug_network_security')], text=True)
                    assert 'debug-overrides' not in xml and 'raw/' not in xml
            if variant == 'release':
                assert re.search(r'android:usesCleartextTraffic[^\n]*0x0', tree)
                assert not re.search(r'android:debuggable[^\n]*0xffffffff', tree)
            else:
                assert re.search(r'android:debuggable[^\n]*0xffffffff', tree)
            for name in archive.namelist():
                assert not re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----', archive.read(name)), name
        print('TLS_TRUST_ISOLATION_OK variant=' + variant)


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        raise SystemExit('Usage: check_debug_ca.py <repo> <aapt> [explicit deployment public CA]')
    check(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) == 4 else None)
