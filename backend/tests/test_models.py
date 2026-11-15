"""Other AOS-Switch models: 2930F-8G-PoE+-2SFP+ (JL258A) and 5406R zl2 chassis (J9850A), on the simulator."""

from sqlalchemy import select

from app.drivers.aruba.aos_switch import cli_commands as cli
from app.drivers.aruba.aos_switch import models as hw
from app.drivers.aruba.aos_switch import system as sysmod
from app.drivers.aruba.aos_switch.capabilities import SUPPORTED_PRODUCTS
from app.drivers.simulator import state as st
from app.models import PoeConfiguration, Switch, SwitchModel, SwitchNeighbor, SwitchPort
from app.services import polling
from tests.conftest import login, make_user

CATS = ("inventory", "availability", "health", "poe", "mac", "lldp", "counters", "inventory")


def test_catalogue_and_helpers():
    assert SUPPORTED_PRODUCTS["JL258A"].startswith("Aruba 2930F 8G PoE+ 2SFP+")
    assert SUPPORTED_PRODUCTS["J9850A"] == "HPE Aruba 5406R zl2 Switch"
    j258 = hw.spec_for("JL258A")
    assert (j258.access_ports, j258.uplink_ports, j258.poe_budget_w) == (8, 2, 125.0)
    assert hw.port_type(j258, "8") == "10/100/1000T PoE+" and hw.port_type(j258, "9") == "SFP+"
    assert hw.port_type(hw.spec_for("JL253A"), "25") == "SFP"
    chassis = hw.spec_for("J9850A")
    assert chassis.modular and chassis.slots == "ABCDEF" and chassis.poe_budget_w is None
    assert hw.port_type(chassis, "A1") == "" and hw.port_type(chassis, "A1", poe_port=True) == "PoE+"
    assert hw.default_if_index("A1") == 1 and hw.default_if_index("B1") == 25 and hw.default_if_index("Trk1") is None
    names = ["B1", "A10", "Trk1", "A2", "10", "2"]
    assert sorted(names, key=hw.port_sort_key) == ["2", "10", "A2", "A10", "B1", "Trk1"]
    for ok in ("A1", "L24", "52", "Trk3"):
        assert cli.port(ok) == ok
    for bad in ("M1", "A1;reload", "GigabitEthernet0/0/1", "A123"):
        try:
            cli.port(bad)
            raise AssertionError(bad)
        except cli.CommandValidationError:
            pass


def test_model_detection_from_sysdescr():
    assert sysmod.parse_sys_descr("HP J9850A Switch 5406Rzl2, revision KB.16.11.0018, ROM KB.16.01.0008") == \
        ("J9850A", "KB.16.11.0018")
    assert sysmod.parse_sys_descr("Aruba JL258A 2930F-8G-PoE+-2SFP+ Switch, revision WC.16.11.0018, ROM WC.16.01.0008") \
        == ("JL258A", "WC.16.11.0018")


def test_reference_models_seeded(db):
    rows = {m.product_number: m for m in db.execute(select(SwitchModel)).scalars()}
    assert rows["JL258A"].port_layout["uplinks"] == [9, 10] and rows["JL258A"].access_ports == 8
    assert rows["J9850A"].port_layout == {"modular": True, "slots": list("ABCDEF")}


def test_fleet_includes_chassis_and_2930f_and_polls(client, db, sim_switches):
    ids = sim_switches(10)
    chassis_id, small_id = ids[-2], ids[-1]
    for c in CATS:
        res = polling.run_category(c, [chassis_id, small_id, ids[0]])
        assert res["failed"] == 0, (c, res)

    small = db.get(Switch, small_id)
    assert small.product_number == "JL258A" and small.firmware == "WC.16.11.0018"
    assert small.model is not None and small.model.access_ports == 8 and small.poe_budget_w == 125.0
    ports = {p.name: p for p in db.execute(select(SwitchPort).where(SwitchPort.switch_id == small_id)).scalars()}
    assert sorted(ports, key=hw.port_sort_key) == [str(n) for n in range(1, 11)]
    assert ports["1"].port_type == "10/100/1000T PoE+" and ports["10"].port_type == "SFP+"
    assert db.query(PoeConfiguration).filter_by(switch_id=small_id).count() == 8

    chassis = db.get(Switch, chassis_id)
    assert chassis.product_number == "J9850A" and chassis.firmware == "KB.16.11.0018"
    assert chassis.model_name == "HPE Aruba 5406R zl2 Switch" and chassis.poe_budget_w == 1100.0
    assert chassis.uplink_ports == ["B1", "B2"]
    cports = {p.name: p for p in db.execute(select(SwitchPort).where(SwitchPort.switch_id == chassis_id)).scalars()}
    assert len(cports) == 32 and cports["B1"].if_index == 25 and cports["A1"].port_number is None
    assert cports["A3"].port_type == "PoE+" and cports["B3"].port_type == ""
    assert cports["B1"].is_uplink
    assert db.query(PoeConfiguration).filter_by(switch_id=chassis_id).count() == 24
    # LLDP chain between models resolves across port naming schemes
    n = db.execute(select(SwitchNeighbor).where(SwitchNeighbor.switch_id == chassis_id,
                                                SwitchNeighbor.local_port == "B2")).scalar_one()
    assert n.remote_port == "9" and n.remote_switch_id == small_id

    make_user(db, "viewer", "viewer1")
    login(client, "viewer1")
    listed = [p["name"] for p in client.get(f"/api/v1/switches/{chassis_id}/ports").json()]
    assert listed[:3] == ["A1", "A2", "A3"] and listed[23:26] == ["A24", "B1", "B2"]


def test_changes_on_slot_ports(client, db, sim_switches):
    ids = sim_switches(10)
    chassis_id = ids[-2]
    for c in ("inventory", "availability", "lldp", "poe", "inventory"):
        polling.run_category(c, [chassis_id])
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "port_description", "switch_ids": [chassis_id],
                                          "params": {"items": [{"port": "A7", "description": "Front desk"}]}})
    assert r.status_code == 201, r.text
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["results"][0]
    r = client.post("/api/v1/jobs", json={"operation": "port_vlan", "switch_ids": [chassis_id],
                                          "params": {"ports": ["A7"], "untagged_vlan": 30}})
    assert r.status_code == 201, r.text
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["results"][0]
    sim = st.store.get(db.get(Switch, chassis_id).mgmt_ip)
    assert sim.ports["A7"].description == "Front desk" and sim.untagged["A7"] == 30
    cfg = sim.running_config()
    assert "module A type j9986a" in cfg and "interface A7" in cfg


def test_faceplate_label_is_app_only_audited_kept_across_polls_and_searchable(client, db, sim_switches):
    from app.models import AuditLog

    ids = sim_switches(1)
    for c in ("inventory", "availability", "mac"):
        polling.run_category(c, ids)
    sim_before = st.store.get(db.get(Switch, ids[0]).mgmt_ip).running_config()
    make_user(db, "viewer", "viewer2")
    login(client, "viewer2")
    url = f"/api/v1/switches/{ids[0]}/ports/3/faceplate-label"
    assert client.put(url, json={"faceplate_label": "PP1-03"}).status_code == 403
    client.post("/api/v1/auth/logout")
    make_user(db, "admin", "ops2")
    login(client, "ops2")
    assert client.put(url, json={"faceplate_label": "bad;label"}).status_code == 422
    assert client.put(url, json={"faceplate_label": "x" * 33}).status_code == 422
    assert client.put(f"/api/v1/switches/{ids[0]}/ports/99/faceplate-label",
                      json={"faceplate_label": "A"}).status_code == 404
    r = client.put(url, json={"faceplate_label": " PP1-03 "})
    assert r.status_code == 200 and r.json()["faceplate_label"] == "PP1-03"
    a = db.query(AuditLog).filter_by(action="port.faceplate_label").one()
    assert a.details == {"port": "3", "old": "", "new": "PP1-03"}
    # kept across polls, never sent to the switch
    for c in ("inventory", "availability", "counters"):
        polling.run_category(c, ids)
    ports = {p["name"]: p for p in client.get(f"/api/v1/switches/{ids[0]}/ports").json()}
    assert ports["3"]["faceplate_label"] == "PP1-03" and ports["4"]["faceplate_label"] == ""
    assert st.store.get(db.get(Switch, ids[0]).mgmt_ip).running_config() == sim_before
    # shown and searchable in Connected devices
    sim = st.store.get(db.get(Switch, ids[0]).mgmt_ip)
    on_port3 = [m for m in sim.macs if m["port"] == "3"]
    found = client.get("/api/v1/devices", params={"q": "pp1-03"}).json()["items"]
    if on_port3:
        assert found and all(d["port"] == "3" and d["faceplate_label"] == "PP1-03" for d in found)
    else:
        assert found == []
    # clearing the label
    assert client.put(url, json={"faceplate_label": ""}).json()["faceplate_label"] == ""


def test_hardware_evidence_recorded_from_physical_report_and_shown(client, db, sim_switches):
    from app.models import AuditLog, ChangeJob, ChangeJobResult, HardwareValidation, SwitchModel
    from app.services import hwvalidate

    ids = sim_switches(1)
    polling.run_category("inventory", ids)
    sw = db.get(Switch, ids[0])
    sw.is_simulated, sw.driver = False, "aruba_aos_s"  # stand-in for a physical switch; the report is constructed
    db.commit()
    report = {"valid_as_hardware_evidence": True, "device": {"product": "JL356A", "firmware": "YC.16.11.0018"},
              "summary": {"passed": 12, "failed": 0}, "checks": []}
    row = hwvalidate.record_evidence(db, sw, report)
    db.commit()
    assert row is not None and db.query(HardwareValidation).count() == 1 and report["validation_id"] == row.id
    ev = db.query(SwitchModel).filter_by(product_number="JL356A").one().hardware_evidence["16.11"]
    assert ev["passed"] == 12 and ev["failed"] == 0 and ev["switch_id"] == sw.id
    assert db.query(AuditLog).filter_by(action="hardware.validate").count() == 1
    # a successful job on the physical switch counts as a verified operation for the model
    job = ChangeJob(operation="port_description", title="t", params={}, status="completed", risk="low",
                    requested_by_name="ops")
    db.add(job)
    db.flush()
    db.add(ChangeJobResult(job_id=job.id, switch_id=sw.id, status="success"))
    db.commit()
    make_user(db, "viewer", "viewer4")
    login(client, "viewer4")
    out = client.get(f"/api/v1/switches/{sw.id}").json()
    assert out["hardware_evidence"]["read_checks_passed"] is True and out["hardware_evidence"]["passed"] == 12
    m = next(x for x in client.get("/api/v1/models").json() if x["product_number"] == "JL356A")
    assert m["verified_operations"] == ["port_description"] and m["hardware_evidence"]["16.11"]["failed"] == 0
    # another firmware train has no evidence
    sw.firmware = "YC.16.10.0012"
    db.commit()
    assert client.get(f"/api/v1/switches/{sw.id}").json()["hardware_evidence"] is None
    # a report that is not hardware evidence is never stored
    assert hwvalidate.record_evidence(db, sw, {"valid_as_hardware_evidence": False}) is None
