import os

from sqlalchemy import select

from app.core.config import get_settings
from app.drivers.simulator import state as st
from app.models import Alert, ConfigBackup, ConfigDiff, Switch
from app.services import backups, polling, storage
from app.services.devices import driver_for
from tests.conftest import login, make_user


def _backup(db, sid, trigger="manual"):
    sw = db.get(Switch, sid)
    with driver_for(db, sw, "monitor") as drv:
        b = backups.take_backup(db, sw, drv, trigger=trigger)
    db.commit()
    return b


def test_backup_is_encrypted_checksummed_and_verified(db, sim_switches):
    sid = sim_switches(1)[0]
    b = _backup(db, sid)
    assert b.verify_status == "verified" and len(b.sha256) == 64
    raw = open(os.path.join(get_settings().storage_path, b.storage_key), "rb").read()
    assert b"hostname" not in raw and raw.startswith(b"ANM1")  # ciphertext at rest
    assert backups.read_text(b).startswith('hostname "SIM-SW-001"')


def test_tampered_backup_detected(db, sim_switches):
    sid = sim_switches(1)[0]
    b = _backup(db, sid)
    path = os.path.join(get_settings().storage_path, b.storage_key)
    data = bytearray(open(path, "rb").read())
    data[-5] ^= 0xFF
    open(path, "wb").write(bytes(data))
    assert backups.verify(db, b) is False and b.verify_status == "failed"


def test_unexpected_change_detected_and_diff(client, db, sim_switches):
    sid = sim_switches(1)[0]
    b1 = _backup(db, sid, "scheduled")
    same = None
    sw = db.get(Switch, sid)
    with driver_for(db, sw, "monitor") as drv:
        same = backups.take_backup(db, sw, drv, trigger="scheduled", dedupe=True)
    assert same.id == b1.id  # unchanged config is not stored twice
    st.mutate(sw.mgmt_ip, lambda s: setattr(s.ports["9"], "description", "changed-on-console"))
    b2 = _backup(db, sid, "scheduled")
    d = db.execute(select(ConfigDiff)).scalar_one()
    assert d.expected is False and d.added_lines >= 1
    assert db.execute(select(Alert).where(Alert.type == "unexpected_config_change")).scalar_one()
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.get("/api/v1/backups/diff", params={"a": b1.id, "b": b2.id}).json()
    assert "+" in r["diff"] and "changed-on-console" in r["diff"] and not r["identical"]
    assert client.get(f"/api/v1/backups/{b2.id}/content").status_code == 200
    assert client.get("/api/v1/backups/drift").json()[0]["expected"] is False


def test_monitor_cannot_read_config(client, db, sim_switches):
    sid = sim_switches(1)[0]
    b = _backup(db, sid)
    make_user(db, "monitor", "mon")
    login(client, "mon")
    assert client.get(f"/api/v1/backups/{b.id}/content").status_code == 403


def test_restore_round_trip_marks_restore_tested(client, db, sim_switches):
    ids = sim_switches(1)
    polling.run_category("inventory", ids)
    b = _backup(db, ids[0])
    assert b.restore_tested is False
    make_user(db, "admin", "ops")
    make_user(db, "super_admin", "boss")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "config_restore", "switch_ids": ids, "acknowledge_risk": True,
                                          "params": {"backup_id": b.id}})
    assert r.json()["risk"] == "critical" and r.json()["status"] == "pending_approval"
    client.post("/api/v1/auth/logout")
    login(client, "boss")
    client.post(f"/api/v1/jobs/{r.json()['id']}/approve", json={})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["results"][0]
    db.refresh(b)
    assert b.restore_tested is True
    sim = st.store.get(db.get(Switch, ids[0]).mgmt_ip)
    assert sim.startup_config is not None and 'hostname "SIM-SW-001"' in sim.startup_config


def test_restore_rejects_foreign_backup(client, db, sim_switches):
    ids = sim_switches(2)
    b = _backup(db, ids[1])
    make_user(db, "super_admin", "boss")
    make_user(db, "super_admin", "boss2")
    login(client, "boss")
    r = client.post("/api/v1/jobs", json={"operation": "config_restore", "switch_ids": [ids[0]], "acknowledge_risk": True,
                                          "params": {"backup_id": b.id}})
    client.post("/api/v1/auth/logout")
    login(client, "boss2")
    client.post(f"/api/v1/jobs/{r.json()['id']}/approve", json={})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and "does not belong" in job["results"][0]["message"]


def test_backup_job_and_retention(client, db, sim_switches):
    from app.services import settings as sysset

    ids = sim_switches(1)
    make_user(db, "admin", "ops")
    login(client, "ops")
    for i in range(4):
        st.mutate(db.get(Switch, ids[0]).mgmt_ip, lambda s, i=i: setattr(s.ports["10"], "description", f"v{i}"))
        r = client.post("/api/v1/jobs", json={"operation": "config_backup", "switch_ids": ids, "params": {}})
        assert client.get(f"/api/v1/jobs/{r.json()['id']}").json()["status"] == "completed"
    assert db.query(ConfigBackup).count() == 4
    sysset.set_value(db, "backups.retention_count", 2, None)
    db.commit()
    assert backups.apply_retention(db) == 2
    db.commit()
    assert db.query(ConfigBackup).count() == 2


def test_storage_key_traversal_rejected(tmp_path):
    import pytest

    s = storage.FilesystemStore(str(tmp_path))
    with pytest.raises(ValueError):
        s.put("../../etc/passwd", b"x")


def test_storage_keys_are_relative_and_safe(tmp_path):
    import pytest

    from app.services.storage import FilesystemStore

    store = FilesystemStore(str(tmp_path))
    store.put("1/a.bin", b"x")
    assert store.keys() == ["1/a.bin"]
    for bad in ["/etc/passwd", "../x", "a/../../x", "a b"]:
        with pytest.raises(ValueError):
            store.put(bad, b"x")


def test_cli_export_import_objects_roundtrip(tmp_path, monkeypatch, capsys):
    import io
    import sys

    from app import cli
    from app.services import storage

    src = storage.FilesystemStore(str(tmp_path / "src"))
    src.put("3/backup-1.enc", b"cipher-1")
    src.put("4/backup-2.enc", b"cipher-2")
    monkeypatch.setattr(storage, "get_store", lambda: src)
    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(out))
    assert cli.main(["export-objects"]) == 0
    sys.stdout.flush()
    dst = storage.FilesystemStore(str(tmp_path / "dst"))
    monkeypatch.setattr(storage, "get_store", lambda: dst)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(out.getvalue())))
    assert cli.main(["import-objects"]) == 0
    assert dst.keys() == ["3/backup-1.enc", "4/backup-2.enc"]
    assert dst.get("4/backup-2.enc") == b"cipher-2"


def test_deleting_switch_removes_its_backup_objects(client, db, sim_switches):
    sid = sim_switches(1)[0]
    b = _backup(db, sid)
    path = os.path.join(get_settings().storage_path, b.storage_key)
    assert os.path.exists(path)
    make_user(db, "super_admin", "root1")
    login(client, "root1")
    r = client.request("DELETE", f"/api/v1/switches/{sid}", json={"confirm_hostname": "SIM-SW-001"})
    assert r.status_code == 200, r.text
    assert not os.path.exists(path)
    assert db.execute(select(ConfigBackup).where(ConfigBackup.switch_id == sid)).first() is None
