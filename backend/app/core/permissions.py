"""Central permission catalogue and the four predefined system roles.

The backend enforces every permission. The frontend only uses the same list to decide what to show.
"""

from __future__ import annotations

from enum import StrEnum


class P(StrEnum):
    # Monitoring / read
    DASHBOARD_VIEW = "dashboard.view"
    SWITCH_VIEW = "switch.view"
    PORT_VIEW = "port.view"
    VLAN_VIEW = "vlan.view"
    POE_VIEW = "poe.view"
    TOPOLOGY_VIEW = "topology.view"
    METRICS_VIEW = "metrics.view"
    REPORT_VIEW = "report.view"
    REPORT_EXPORT = "report.export"
    DEVICE_VIEW = "device.view"  # MAC tables / connected devices
    ALERT_VIEW = "alert.view"
    ALERT_ACK = "alert.ack"
    EVENT_VIEW = "event.view"

    # Operations
    SWITCH_MANAGE = "switch.manage"  # add/edit inventory, monitoring toggle, discovery
    SWITCH_DELETE = "switch.delete"
    PORT_MANAGE = "port.manage"
    VLAN_MANAGE = "vlan.manage"
    POE_MANAGE = "poe.manage"
    SECURITY_MANAGE = "netsec.manage"  # switch security features
    BULK_EXECUTE = "bulk.execute"
    JOB_VIEW = "job.view"
    CHANGE_APPROVE = "change.approve"
    BACKUP_VIEW = "backup.view"
    BACKUP_MANAGE = "backup.manage"
    BACKUP_EXPORT = "backup.export"  # download raw configuration text
    CONFIG_RESTORE = "config.restore"
    TEMPLATE_MANAGE = "template.manage"
    ALERT_RULE_MANAGE = "alert_rule.manage"
    AUDIT_VIEW_OPERATIONAL = "audit.view_operational"

    # Administration
    USER_VIEW = "user.view"
    USER_MANAGE = "user.manage"
    USER_MANAGE_SUPERADMIN = "user.manage_superadmin"
    AUDIT_VIEW_ALL = "audit.view_all"
    SETTINGS_VIEW = "settings.view"
    SETTINGS_MANAGE = "settings.manage"  # system-wide security/auth settings
    OPERATIONAL_SETTINGS_MANAGE = "settings.operational"  # polling, backup schedule
    CREDENTIAL_MANAGE = "credential.manage"
    INTEGRATION_MANAGE = "integration.manage"
    SYSTEM_HEALTH_VIEW = "system.health"


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MONITOR = "monitor"
    VIEWER = "viewer"


ROLE_ORDER = [Role.SUPER_ADMIN, Role.ADMIN, Role.MONITOR, Role.VIEWER]

_VIEWER = {
    P.DASHBOARD_VIEW, P.SWITCH_VIEW, P.PORT_VIEW, P.VLAN_VIEW, P.POE_VIEW, P.TOPOLOGY_VIEW,
    P.METRICS_VIEW, P.REPORT_VIEW,
}
_MONITOR = _VIEWER | {
    P.DEVICE_VIEW, P.ALERT_VIEW, P.ALERT_ACK, P.EVENT_VIEW, P.REPORT_EXPORT,
}
_ADMIN = _MONITOR | {
    P.SWITCH_MANAGE, P.SWITCH_DELETE, P.PORT_MANAGE, P.VLAN_MANAGE, P.POE_MANAGE, P.SECURITY_MANAGE,
    P.BULK_EXECUTE, P.JOB_VIEW, P.BACKUP_VIEW, P.BACKUP_MANAGE, P.BACKUP_EXPORT, P.CONFIG_RESTORE,
    P.TEMPLATE_MANAGE, P.ALERT_RULE_MANAGE, P.AUDIT_VIEW_OPERATIONAL, P.USER_VIEW, P.USER_MANAGE,
    P.OPERATIONAL_SETTINGS_MANAGE, P.SETTINGS_VIEW, P.SYSTEM_HEALTH_VIEW,
}
_SUPER = set(P)

ROLE_PERMISSIONS: dict[Role, frozenset[P]] = {
    Role.SUPER_ADMIN: frozenset(_SUPER),
    Role.ADMIN: frozenset(_ADMIN),
    Role.MONITOR: frozenset(_MONITOR),
    Role.VIEWER: frozenset(_VIEWER),
}

ROLE_DESCRIPTIONS = {
    Role.SUPER_ADMIN: "Full unrestricted application administration",
    Role.ADMIN: "Full operational network administration without security administration",
    Role.MONITOR: "Monitoring, alert acknowledgement and report export",
    Role.VIEWER: "Read-only access to dashboards and inventory",
}


def permissions_for(role: str) -> frozenset[P]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def has_permission(role: str, perm: P) -> bool:
    return perm in permissions_for(role)


def can_assign_role(actor_role: str, target_role: str) -> bool:
    """Super Admin may assign any role; Admin may manage only Monitor/Viewer users; others nothing."""
    if actor_role == Role.SUPER_ADMIN:
        return True
    if actor_role == Role.ADMIN:
        return target_role in (Role.MONITOR, Role.VIEWER)
    return False
