"""Driver tests against the simulator's REST/SNMP/SSH endpoints and protocol edge cases."""

import base64

import httpx
import pytest

from app.drivers.aruba.aos_switch import cli_commands as cli
from app.drivers.aruba.aos_switch import system as sysmod
from app.drivers.aruba.aos_switch.capabilities import capabilities_for, firmware_train
from app.drivers.aruba.aos_switch.configuration import normalize_config
from app.drivers.aruba.aos_switch.rest_client import RestClient
from app.drivers.base import DriverError
from app.drivers.simulator import driver as simdrv
from app.drivers.simulator import state as st

IP = "198.18.0.1"
C = simdrv.SIM_CREDENTIALS


def build(**kw):
    st.get_or_create(IP, 1, 2)
    args = dict(rest=(C["rest"]["username"], C["rest"]["password"]),
                snmp=(C["snmpv3"]["username"], C["snmpv3"]["auth_password"], C["snmpv3"]["priv_password"]),
                ssh=(C["ssh"]["username"], C["ssh"]["password"]), host_key_trusted=True)
    args.update(kw)
    return simdrv.build(IP, **args)


def test_rest_authentication_and_version_negotiation():
    st.get_or_create(IP, 1, 1)
    rc = RestClient(IP, C["rest"]["username"], C["rest"]["password"], transport=httpx.MockTransport(
        __import__("app.drivers.simulator.rest", fromlist=["SimRestHandler"]).SimRestHandler(IP)))
    rc.login()
    assert rc.api_version == "v7"
    assert rc.get("/system")["name"] == "SIM-SW-001"
    rc.close()
    bad = RestClient(IP, "x", "y", transport=httpx.MockTransport(
        __import__("app.drivers.simulator.rest", fromlist=["SimRestHandler"]).SimRestHandler(IP)))
    with pytest.raises(DriverError) as e:
        bad.login()
    assert e.value.code == "auth_failed"


def test_rest_session_expiry_relogin():
    calls = {"login": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/rest/version":
            return httpx.Response(200, json={"version_element": [{"version": "v7"}]})
        if req.url.path.endswith("/login-sessions"):
            calls["login"] += 1
            return httpx.Response(201, json={"cookie": f"sessionId=s{calls['login']}"})
        if req.headers.get("cookie") == "sessionId=s1":
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(200, json={"ok": True})

    rc = RestClient("10.0.0.1", "u", "p", transport=httpx.MockTransport(handler))
    assert rc.get("/system") == {"ok": True}
    assert calls["login"] == 2


def test_rest_rejects_unsupported_versions():
    def handler(req):
        return httpx.Response(200, json={"version_element": [{"version": "v1"}, {"version": "v2"}]})

    with pytest.raises(DriverError) as e:
        RestClient("10.0.0.1", "u", "p", transport=httpx.MockTransport(handler)).login()
    assert e.value.code == "rest_version"


def test_rest_timeout_is_structured_and_retried():
    attempts = {"n": 0}

    def handler(req):
        if req.url.path == "/rest/version":
            return httpx.Response(200, json={"version_element": [{"version": "v7"}]})
        if req.url.path.endswith("login-sessions"):
            return httpx.Response(201, json={"cookie": "sessionId=a"})
        attempts["n"] += 1
        raise httpx.ReadTimeout("slow", request=req)

    rc = RestClient("10.0.0.1", "u", "p", transport=httpx.MockTransport(handler), max_retries=2)
    with pytest.raises(DriverError) as e:
        rc.get("/ports")
    assert e.value.code == "timeout" and e.value.retriable and attempts["n"] == 3


def test_reads_parse_device_data():
    d = build()
    caps = d.probe()
    assert caps["rest"] and caps["snmp"] and caps["ssh"] and all(caps["resources"].values())
    info = d.get_system()
    assert info.product_number == "JL356A" and info.firmware == "YC.16.11.0018" and info.uptime_seconds > 0
    assert info.base_mac == "02:5a:00:00:01:00"
    ports = d.get_ports()
    assert [p.name for p in ports] == [str(i) for i in range(1, 29)]
    assert all(p.if_index == int(p.name) for p in ports)
    counters = d.get_port_counters()
    assert len(counters) == 28  # VLAN interfaces (ifType 136) filtered out
    vlans = {v.vlan_id: v for v in d.get_vlans()}
    assert vlans[99].is_management and set(vlans) == {1, 10, 20, 30, 99}
    poe = d.get_poe_ports()
    assert len(poe) == 24 and {p.priority for p in poe} == {"low"}
    assert d.get_poe_summary().budget_w == 370.0
    macs = d.get_mac_table()
    assert macs and all(len(m.mac) == 17 for m in macs)
    assert d.get_lldp_neighbors()
    cfg = d.get_running_config()
    assert cfg.text.startswith('hostname "SIM-SW-001"') and cfg.source == "rest-cli"
    h = d.get_health()
    assert 0 < h.cpu_pct < 100 and 0 < h.mem_pct < 100 and h.temperature_c is not None


def test_fallback_to_snmp_and_ssh_when_rest_resource_missing():
    st.get_or_create(IP, 1, 1)
    st.mutate(IP, lambda s: setattr(s, "unsupported_rest", ["/mac-table", "/lldp", "/vlans", "/cli", "/ports"]))
    d = build()
    assert d.get_mac_table()  # SNMP Q-BRIDGE
    assert d.get_lldp_neighbors()  # SNMP LLDP-MIB
    assert {v.vlan_id for v in d.get_vlans()} == {1, 10, 20, 30, 99}
    assert d.get_running_config().source == "ssh"
    r = d.set_port_admin("4", False)  # REST /ports unsupported -> SSH CLI
    assert r.protocol == "ssh"
    assert {p.name: p.admin_up for p in d.get_port_status()}["4"] is False
    assert d.ctx.probed.get("mac.read") is False


def test_writes_and_readback():
    d = build()
    d.set_port_description("7", "Reception PC")
    d.set_port_speed_duplex("7", "100-full")
    p = {x.name: x for x in d.get_ports()}["7"]
    assert p.description == "Reception PC" and p.config_mode == "100-full"
    d.create_vlan(200, "GUEST")
    d.set_port_vlan("7", 200, "untagged")
    d.set_port_vlan("8", 200, "tagged")
    mem = d.get_vlan_memberships()
    assert any(m.port == "7" and m.vlan_id == 200 and m.mode == "untagged" for m in mem)
    d.remove_port_vlan("8", 200)
    assert not any(m.port == "8" and m.vlan_id == 200 for m in d.get_vlan_memberships())
    d.set_poe("3", enabled=False)
    d.set_poe("4", allocation_method="value", allocated_power_w=15)
    poe = {x.port: x for x in d.get_poe_ports()}
    assert poe["3"].enabled is False and poe["4"].allocation_method == "value"
    d.restart_poe("5")
    d.delete_vlan(200)
    assert 200 not in {v.vlan_id for v in d.get_vlans()}


def test_management_vlan_cannot_be_deleted_on_device():
    d = build()
    with pytest.raises(DriverError):
        d.delete_vlan(99)


def test_offline_switch_raises_unreachable():
    d = build()
    st.mutate(IP, lambda s: setattr(s, "offline", True))
    with pytest.raises(DriverError) as e:
        d.get_port_status()
    assert e.value.retriable


def test_snmp_wrong_credentials():
    d = build(snmp=("sim-snmp", "wrong-pass-123", "wrong-pass-456"))
    with pytest.raises(DriverError) as e:
        d.get_health()
    assert e.value.code == "auth_failed"


def test_ssh_untrusted_host_key_refused():
    d = build(host_key_trusted=False)
    with pytest.raises(DriverError) as e:
        d.ssh.show("show version")
    assert e.value.code == "host_key_untrusted"


def test_ssh_only_allowlisted_show_commands():
    d = build()
    with pytest.raises(DriverError):
        d.ssh.show("show tech all")


@pytest.mark.parametrize("bad", ['1; reload', "1\nreload", "1 | include x", "../etc", "Trk1;", "", "999"])
def test_port_injection_rejected(bad):
    with pytest.raises(DriverError):
        cli.cmd_port_admin(bad, True)


@pytest.mark.parametrize("bad", ['x"; reload', "a\nb", "name`x`", "x" * 65])
def test_description_injection_rejected(bad):
    with pytest.raises(DriverError):
        cli.cmd_port_description("1", bad)


def test_vlan_validation():
    for bad in (0, 4095, -1, True, "10"):
        with pytest.raises(DriverError):
            cli.vlan_id(bad)
    with pytest.raises(DriverError):
        cli.cmd_vlan_delete(1)
    with pytest.raises(DriverError):
        cli.vlan_name("bad name")
    assert cli.cmd_vlan_create(10, "DATA") == ["vlan 10", 'name "DATA"', "exit"]


def test_security_command_validation():
    with pytest.raises(DriverError):
        cli.cmd_snmpv3_user("mon", "md5", "Passphrase1", "aes", "Passphrase2")
    with pytest.raises(DriverError):
        cli.cmd_snmpv3_user("mon", "sha", "short", "aes", "Passphrase2")
    with pytest.raises(DriverError):
        cli.cmd_radius_server("10.0.0.1", "key with space")
    with pytest.raises(DriverError):
        cli.cmd_sntp(["10.0.0.1; reload"])
    with pytest.raises(DriverError):
        cli.assert_safe_line("vlan 10; reload")


def test_sys_descr_parsing_and_capabilities():
    pn, fw = sysmod.parse_sys_descr("Aruba JL356A 2540-24G-PoE+-4SFP+ Switch, revision YC.16.11.0018, ROM YC.16.01.0002")
    assert pn == "JL356A" and fw == "YC.16.11.0018"
    assert firmware_train("YC.16.11.0018") == "16.11"
    caps = capabilities_for("YC.16.11.0018")
    assert all(c.evidence != "verified" for c in caps.values()), "nothing may claim hardware verification"


def test_config_normalisation_strips_volatile_header():
    raw = "Running configuration:\n\n; JL356A Configuration Editor; Created on release #YC.16.11.0018\n; Ver #14:01\nhostname \"x\"\nvlan 1\n"
    assert normalize_config(raw) == 'hostname "x"\nvlan 1\n'


def test_rest_cli_result_decoding():
    def handler(req):
        if req.url.path == "/rest/version":
            return httpx.Response(200, json={"version_element": [{"version": "v7"}]})
        if req.url.path.endswith("login-sessions"):
            return httpx.Response(201, json={"cookie": "sessionId=a"})
        return httpx.Response(200, json={"status": "CCS_SUCCESS",
                                         "result_base64_encoded": base64.b64encode(b"hello").decode()})

    assert RestClient("10.0.0.1", "u", "p", transport=httpx.MockTransport(handler)).cli("show version") == "hello"
