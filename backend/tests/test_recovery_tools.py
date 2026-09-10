import importlib.util
from pathlib import Path
import pytest
from cryptography.fernet import Fernet

spec=importlib.util.spec_from_file_location("recovery_drill",Path(__file__).resolve().parents[2]/"scripts/recovery_drill.py")
recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)


def test_backup_encryption_roundtrip_tampering_truncation_and_wrong_key(tmp_path,monkeypatch):
    monkeypatch.setattr(recovery,"CHUNK",32)
    source=tmp_path/"source";source.write_bytes(bytes(range(256))*3)
    key=Fernet.generate_key()
    encrypted=tmp_path/"encrypted"
    recovery.crypt_file(source,encrypted,key)
    # Fernet framing has fixed overhead, so restore the normal maximum-frame bound.
    monkeypatch.setattr(recovery,"CHUNK",8*1024*1024)
    output=tmp_path/"output";recovery.crypt_file(encrypted,output,key,decrypt=True)
    assert output.read_bytes()==source.read_bytes()
    with pytest.raises(FileExistsError): recovery.crypt_file(source,encrypted,key)
    variants=[encrypted.read_bytes()[:-20],encrypted.read_bytes()+b"extra"]
    changed=bytearray(encrypted.read_bytes());changed[100]^=1;variants.append(bytes(changed))
    for i,data in enumerate(variants):
        bad=tmp_path/f"bad{i}";bad.write_bytes(data)
        with pytest.raises(Exception): recovery.crypt_file(bad,tmp_path/f"out{i}",key,decrypt=True)
    with pytest.raises(Exception): recovery.crypt_file(encrypted,tmp_path/"wrong",Fernet.generate_key(),decrypt=True)
