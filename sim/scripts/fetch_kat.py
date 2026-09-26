"""Re-import pinned NIST KAT data. Normal tests use committed files offline."""

import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
ACVP = "https://raw.githubusercontent.com/usnistgov/ACVP-Server/65370b861b96efd30dfe0daae607bde26a78a5c8/gen-val/json-files/"
SOURCES = {
    # NIST's download endpoint returned HTTP 403; use its unchanged .rsp copy
    # maintained by the AES reference's upstream project, pinned by commit/hash.
    "gcm": ("https://raw.githubusercontent.com/pyca/cryptography/8e03e30e3aae01632a697e903e3593c924f0139d/vectors/cryptography_vectors/ciphers/AES/GCM/gcmEncryptExtIV128.rsp",
            "30156236f768b0d81e58a3e5bd3bd79ce294cf9ef0ba0a84cf7b869c89ebd9fd"),
    "keygen": (ACVP + "ML-KEM-keyGen-FIPS203/internalProjection.json",
               "0fdca41ed30f49c828af80c73a6424ece3accc1e3430ae14492363aaadeb0e48"),
    "kem": (ACVP + "ML-KEM-encapDecap-FIPS203/internalProjection.json",
            "4b5afd6c7075b1ffebc099a70dcf907b189daadd42921223127732e3ec83c333"),
}


def fetch(name):
    url, expected = SOURCES[name]
    request = urllib.request.Request(url, headers={"User-Agent": "EYEPQC-KAT/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"source SHA-256 mismatch: {name}")
    return data


def parse_rsp(text):
    metadata, record, records = {}, {}, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            if record:
                records.append(record)
                record = {}
            key, value = line[1:-1].split("=", 1)
            metadata[key.strip()] = int(value)
        else:
            key, value = (part.strip() for part in line.split("=", 1))
            if key == "Count":
                if record:
                    records.append(record)
                record = {"parameters": metadata.copy()}
            record[key] = value.lower()
    if record:
        records.append(record)
    return records


def main():
    gcm = []
    for record in parse_rsp(fetch("gcm").decode("ascii")):
        params = record["parameters"]
        if (record["Count"] == "0" and params["Keylen"] == 128 and
            params["IVlen"] == 96 and params["Taglen"] == 128 and
            params["AADlen"] <= 512 and params["PTlen"] <= 11200):
            gcm.append({"parameters": params, "count": 0,
                        **{new: record[old] for new, old in (
                            ("key", "Key"), ("nonce", "IV"), ("plaintext", "PT"),
                            ("aad", "AAD"), ("ciphertext", "CT"), ("tag", "Tag"))}})
    keygen_data = json.loads(fetch("keygen"))
    kem_data = json.loads(fetch("kem"))
    keygen = [v for group in keygen_data["testGroups"]
              if group["parameterSet"] == "ML-KEM-512"
              for v in group["tests"]]
    encapsulation, decapsulation = [], []
    for group in kem_data["testGroups"]:
        if group["parameterSet"] != "ML-KEM-512":
            continue
        for v in group["tests"]:
            if group["function"] == "encapsulation":
                encapsulation.append(v)
            elif group["function"] == "decapsulation":
                decapsulation.append({**v, "dk": group["dk"]})
    if not gcm or (len(keygen), len(encapsulation), len(decapsulation)) != (25, 25, 10):
        raise ValueError("unexpected pinned NIST corpus layout")
    files = {
        "nist_gcm.json": {"schema": 1, "source": "NIST CAVS 14.0 gcmEncryptExtIV128.rsp",
                          "selection": "Count=0, AES-128, IV=96, Tag=128, AAD<=512 bits",
                          "vectors": gcm},
        "nist_mlkem512.json": {"schema": 1, "source": "NIST ACVP v1.1.0.35 / FIPS203",
                               "keygen": keygen, "encapsulation": encapsulation,
                               "decapsulation": decapsulation},
    }
    output = ROOT / "data" / "kat"
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, value in files.items():
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        (output / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    provenance = {"sources": {k: {"url": u, "sha256": h} for k, (u, h) in SOURCES.items()},
                  "files": hashes,
                  "original_gcm": "https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Algorithm-Validation-Program/documents/mac/gcmtestvectors.zip"}
    (output / "sources.json").write_bytes((json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode())
    print(f"Imported {len(gcm)} NIST GCM and 25/25/10 ML-KEM-512 KAT cases")


if __name__ == "__main__":
    main()
