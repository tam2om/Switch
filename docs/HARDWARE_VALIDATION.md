# Hardware validation procedure

**Status: pending. No physical switch has been tested.** This procedure must be completed on a lab switch before
the application manages production switches. Do not run it on a production switch.

## 1. Lab setup

* One Aruba 2540 24G PoE+ (JL356A) on YC.16.11.0018, not connected to production, reachable from the application
  host. Console access to the switch.
* A test PoE device on one port (an access point or IP phone) and one LLDP neighbour on an uplink.
* The switch prepared as in DEPLOYMENT.md section 4 (operator and manager accounts, SNMPv3 user, `rest-interface`,
  `ip ssh`, `ip ssh filetransfer` for restore tests).
* Before starting: `show running-config` saved from the console, so the switch can be reset by hand.

## 2. Read-only validation (safe)

1. Add the switch in the application with its monitoring credentials. On the Security tab, fetch the SSH host key,
   compare it with `show crypto host-public-key fingerprint` on the console, then trust it.
2. Run the harness on the host:

   ```sh
   docker compose exec backend docker-entrypoint.sh cli hw-validate <switch-id> > hw-<serial>-$(date +%F).json
   ```

   It calls only read operations (probe, system, health, ports, counters, VLANs, VLAN membership, PoE ports and
   summary, MAC table, LLDP, running and startup configuration) with the monitoring credential and records each
   result, error and duration. Exit code 0 means every check passed. If no monitoring SSH account is set, the two
   configuration reads use the configuration SSH account through a read-only session that refuses every
   configuration command.

   A report from a physical switch that identified itself is stored as evidence (table `hardware_validations`,
   audit action `hardware.validate`) and recorded on the model for that firmware train. When every check passed,
   switches of that model on that firmware train show "validated on hardware (read-only)" instead of
   "hardware validation pending". Change operations are listed as verified on a model under Administration >
   Inventory once a job on a physical switch of that model has applied the change and read it back.
3. Check the report:
   * `simulated` is `false` and `valid_as_hardware_evidence` is `true` (the switch reported product and firmware).
   * `device.product` is `JL356A` and `device.firmware` is `YC.16.11.0018`.
   * `probe.rest_version` is the version you expect, and `probe.resources` shows which REST resources answered.
   * Compare the counts with the console: `show interfaces brief` (28 ports), `show vlans`,
     `show power-over-ethernet brief`, `show mac-address`, `show lldp info remote-device`.
4. Leave the switch polled for at least 24 hours and compare the charts with the switch (CPU, memory, traffic on a
   loaded port, PoE draw).

## 3. Change validation (changes the lab switch)

For each operation, request it in the application, let it run, then confirm on the console and record the result.
Every run should show: pre-change backup, change, read-back verification, write memory.

| # | Operation | Console check |
|---|---|---|
| 1 | Port description on an unused port | `show running-config interface <p>` |
| 2 | Port disable, then enable | `show interfaces brief` |
| 3 | Port speed/duplex (e.g. 100-full, then auto) | `show interfaces brief` |
| 4 | VLAN create, rename, delete (unused ID) | `show vlans` |
| 5 | Port untagged VLAN, then tagged VLAN | `show vlans <id>` |
| 6 | PoE disable/enable, priority, allocation | `show power-over-ethernet <p>` |
| 7 | PoE restart (device should reboot) | the powered device's logs |
| 8 | SNTP server | `show sntp` |
| 9 | SNMPv3 user (new user, then remove) | `show snmpv3 user` |
| 10 | Authorized managers (add the app host first!) | `show ip authorized-managers` |
| 11 | Port security, STP protection, DHCP snooping, AAA server, SSH hardening | `show running-config` |
| 12 | Configuration backup, then compare, then verify | application only |
| 13 | Configuration restore (startup), reload from the console in the lab | `show config` before reload |
| 14 | A change that must fail (invalid VLAN on a trunk); the job must stop and report it | job view |
| 15 | Bulk change in Pro mode with "canary first" and "stop after 1 failure" | job view |

## 4. Recording the evidence

* Keep the harness JSON, a copy of the job views (or `GET /api/v1/jobs/<id>`), and the console outputs.
* For each capability confirmed, change its evidence from `documented` to `verified` in
  `backend/app/drivers/aruba/aos_switch/capabilities.py` in a reviewed pull request that attaches the evidence, and
  update [HARDWARE_COMPATIBILITY.md](HARDWARE_COMPATIBILITY.md).
* Any mismatch (wrong REST field, different CLI syntax, missing resource) is fixed in the driver with a test that
  reproduces the real device response, before the evidence is marked verified.

## 5. Rollout after validation

1. Monitoring only on a pilot group of 3–5 production switches (monitoring credentials only) for one week.
2. Configuration credentials on the pilot group; low-risk changes only (descriptions), then VLAN changes.
3. Remaining switches in groups, keeping the approval threshold at "high" or lower.
