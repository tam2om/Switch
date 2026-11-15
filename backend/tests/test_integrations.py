import httpx

from app.integrations import service
from app.models import Switch
from tests.conftest import login, make_user


def zabbix_transport():
    def handler(req: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(req.content)
        m = body["method"]
        if m == "apiinfo.version":
            return httpx.Response(200, json={"result": "7.0.0", "id": 0})
        assert req.headers["authorization"] == "Bearer zbx-token"
        if m == "hostgroup.get":
            return httpx.Response(200, json={"result": [{"groupid": "5"}], "id": body["id"]})
        if m == "host.get":
            return httpx.Response(200, json={"id": body["id"], "result": [
                {"hostid": "10101", "host": "core-sw-01", "interfaces": [{"ip": "10.10.0.11", "main": "1"}]},
                {"hostid": "10102", "host": "edge-sw-02", "interfaces": [{"ip": "10.10.0.12", "main": "1"}]}]})
        if m == "problem.get":
            return httpx.Response(200, json={"id": body["id"], "result": [
                {"eventid": "1", "name": "High ICMP ping loss", "severity": "3", "clock": "1700000000",
                 "hosts": [{"hostid": "10101"}]}]})
        return httpx.Response(200, json={"error": {"message": "unknown"}})

    return httpx.MockTransport(handler)


def airwave_transport():
    xml = """<?xml version="1.0"?><amp:amp_ap_list xmlns:amp="http://www.airwave.com">
      <ap id="77"><name>edge-sw-03</name><lan_ip>10.10.0.13</lan_ip><model>Aruba 2540 24G PoE+</model>
      <device_category>switch</device_category><is_up>true</is_up></ap>
      <ap id="78"><name>AP-1</name><lan_ip>10.20.0.5</lan_ip><model>AP-515</model>
      <device_category>thin_ap</device_category></ap></amp:amp_ap_list>"""

    def handler(req):
        if req.url.path == "/LOGIN":
            return httpx.Response(302, headers={"set-cookie": "Mercury::Handler::AuthCookieHandler_AMPAuth=abc; path=/",
                                                "location": "/"})
        if req.url.path == "/ap_list.xml":
            return httpx.Response(200, text=xml)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_zabbix_sync_links_and_imports(db, monkeypatch):
    db.add(Switch(hostname="core-sw-01", mgmt_ip="10.10.0.11"))
    row = service.get_or_create(db, "zabbix")
    row.enabled, row.url = True, "https://zabbix.example.com/zabbix"
    service.set_secret(row, "zbx-token")
    row.params = {"host_group": "Switches"}
    db.commit()
    assert "zbx-token" not in row.secret_enc
    t = zabbix_transport()
    assert service.test(db, "zabbix", transport=t)["version"] == "7.0.0"
    res = service.sync(db, "zabbix", import_new=True, transport=t)
    db.commit()
    assert res["linked"] == 2 and res["imported"] == 1 and res["problems"] == 1
    sw = db.query(Switch).filter_by(mgmt_ip="10.10.0.11").one()
    assert sw.external_ids["zabbix"]["id"] == "10101" and sw.external_ids["zabbix"]["problems"][0]["severity"] == 3
    assert "hostids" in sw.external_ids["zabbix"]["url"]


def test_airwave_preview_filters_switches(db):
    row = service.get_or_create(db, "airwave")
    row.enabled, row.url, row.username = True, "https://airwave.example.com", "api"
    service.set_secret(row, "pw")
    db.commit()
    items = service.preview(db, "airwave", transport=airwave_transport())
    assert [i["name"] for i in items] == ["edge-sw-03"]


def test_airwave_rejects_xml_entities():
    import pytest

    from app.integrations.airwave import _safe_parse
    from app.integrations.zabbix import IntegrationError

    with pytest.raises(IntegrationError):
        _safe_parse('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')


def test_integration_api_requires_https_and_superadmin(client, db):
    make_user(db, "admin", "ops")
    login(client, "ops")
    assert client.get("/api/v1/integrations").status_code == 403
    client.post("/api/v1/auth/logout")
    make_user(db, "super_admin", "boss")
    login(client, "boss")
    assert client.put("/api/v1/integrations/zabbix", json={"url": "http://zabbix"}).status_code == 422
    r = client.put("/api/v1/integrations/zabbix", json={"enabled": True, "url": "https://zabbix.example.com",
                                                       "secret": "tok"})
    assert r.status_code == 200 and r.json()["has_secret"] and "tok" not in r.text
