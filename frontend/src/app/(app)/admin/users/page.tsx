"use client";

import { useState } from "react";
import { roleLabel } from "@/components/AppShell";
import {
  Badge, Button, Card, Checkbox, ConfirmDialog, Empty, ErrorBox, Field, Input, Loadable, Modal, Notice, PageHeader, Pagination,
  Select, Table, Td, Th, useToast,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, PASSWORD_HINT, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AuditRow, Page, RoleName, User } from "@/lib/types";

interface RoleInfo {
  name: RoleName;
  description: string;
  permissions: string[];
  assignable: boolean;
}

function UserEditor({ initial, roles, onClose, onSaved }: { initial: User | "new"; roles: RoleInfo[]; onClose: () => void; onSaved: () => void }) {
  const u = initial === "new" ? null : initial;
  const assignable = roles.filter((r) => r.assignable);
  const [f, setF] = useState({
    username: u?.username || "",
    full_name: u?.full_name || "",
    email: u?.email || "",
    role: (u?.role || assignable[assignable.length - 1]?.name || "viewer") as RoleName,
    password: "",
    must_change_password: true,
    is_active: u?.is_active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (u) {
        await api(`/users/${u.id}`, { method: "PATCH", body: { full_name: f.full_name, email: f.email || null, role: f.role, is_active: f.is_active } });
      } else {
        await api("/users", { method: "POST", body: { username: f.username, full_name: f.full_name, email: f.email || null, role: f.role, password: f.password, must_change_password: f.must_change_password } });
      }
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const roleOptions = u && !assignable.find((r) => r.name === u.role) ? [...assignable, roles.find((r) => r.name === u.role)!] : assignable;
  return (
    <Modal open title={u ? `Edit ${u.username}` : "Create user"} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>{u ? "Save" : "Create user"}</Button></>}>
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Username" htmlFor="u-name" hint={u ? undefined : "3–64 characters: letters, digits, . _ -"}>
            <Input id="u-name" value={f.username} disabled={!!u} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" />
          </Field>
          <Field label="Full name" htmlFor="u-full">
            <Input id="u-full" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
          </Field>
          <Field label="Email" htmlFor="u-email">
            <Input id="u-email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          </Field>
          <Field label="Role" htmlFor="u-role">
            <Select id="u-role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as RoleName })}>
              {roleOptions.map((r) => (
                <option key={r.name} value={r.name} disabled={!r.assignable}>{roleLabel(r.name)}</option>
              ))}
            </Select>
          </Field>
        </div>
        <p className="text-xs text-muted">{roles.find((r) => r.name === f.role)?.description}</p>
        {!u && (
          <>
            <Field label="Initial password" htmlFor="u-pw" hint={PASSWORD_HINT}>
              <Input id="u-pw" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
            </Field>
            <Checkbox label="User must change the password at first sign-in" checked={f.must_change_password} onChange={(v) => setF({ ...f, must_change_password: v })} />
          </>
        )}
        {u && <Checkbox label="Account active" checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} />}
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

function SetPassword({ user, onClose }: { user: User; onClose: () => void }) {
  const toast = useToast();
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Modal
      open
      title={`Set password for ${user.username}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await api(`/users/${user.id}/password`, { method: "POST", body: { password: pw } });
                toast("ok", "Password set. The user must change it at next sign-in and existing sessions were ended.");
                onClose();
              } catch (e) {
                setErr(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            Set password
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Temporary password" htmlFor="sp-pw" hint={PASSWORD_HINT}>
          <Input id="sp-pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />
        </Field>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

function Activity({ user, onClose }: { user: User; onClose: () => void }) {
  const { data, error } = useApi<AuditRow[]>(`/users/${user.id}/activity`, { limit: 100 });
  return (
    <Modal open wide title={`Activity of ${user.username}`} onClose={onClose}>
      <Loadable data={data} error={error}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No recorded activity.</Empty>
          ) : (
            <Table>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <Td className="whitespace-nowrap text-xs">{fmtDate(r.ts)}</Td>
                    <Td className="text-xs">{r.action}</Td>
                    <Td><Badge tone={r.result === "success" ? "ok" : "bad"}>{r.result}</Badge></Td>
                    <Td className="text-xs text-muted">{r.ip}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )
        }
      </Loadable>
    </Modal>
  );
}

export default function UsersPage() {
  const { can, me } = useAuth();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useApi<Page<User>>("/users", { q, role, active, page, page_size: 50 });
  const roles = useApi<RoleInfo[]>("/users/roles");
  const [edit, setEdit] = useState<User | "new" | null>(null);
  const [del, setDel] = useState<User | null>(null);
  const [pw, setPw] = useState<User | null>(null);
  const [act, setAct] = useState<User | null>(null);
  const [token, setToken] = useState<{ user: string; path: string; hours: number } | null>(null);

  const action = async (u: User, path: string, msg: string) => {
    try {
      await api(`/users/${u.id}/${path}`, { method: "POST" });
      toast("ok", msg);
      mutate();
    } catch (e) {
      toast("bad", errorMessage(e));
    }
  };

  return (
    <div>
      <PageHeader title="Users" subtitle="Local accounts and roles" actions={can("user.manage") && <Button variant="primary" onClick={() => setEdit("new")}>Create user</Button>} />
      {roles.data && (
        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {roles.data.map((r) => (
            <div key={r.name} className="rounded-lg border border-line bg-panel p-3 text-sm">
              <div className="font-medium">{roleLabel(r.name)}</div>
              <div className="text-xs text-muted">{r.description}</div>
            </div>
          ))}
        </div>
      )}
      <Card bodyClassName="p-0">
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          <Input className="w-64" placeholder="Search username, name, email" aria-label="Search users" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <Select className="w-40" aria-label="Role" value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}>
            <option value="">All roles</option>
            {roles.data?.map((r) => <option key={r.name} value={r.name}>{roleLabel(r.name)}</option>)}
          </Select>
          <Select className="w-36" aria-label="Status" value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}>
            <option value="">Any status</option>
            <option value="true">Active</option>
            <option value="false">Disabled</option>
          </Select>
        </div>
        <Loadable data={data} error={error} retry={() => mutate()}>
          {(d) =>
            d.items.length === 0 ? (
              <Empty>No users match.</Empty>
            ) : (
              <>
                <Table>
                  <thead>
                    <tr>
                      <Th>User</Th>
                      <Th>Role</Th>
                      <Th>Status</Th>
                      <Th>2FA</Th>
                      <Th>Last sign-in</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((u) => (
                      <tr key={u.id}>
                        <Td>
                          <span className="font-medium">{u.username}</span> {u.id === me?.id && <Badge>you</Badge>}
                          <div className="text-xs text-muted">{[u.full_name, u.email].filter(Boolean).join(" · ")}</div>
                        </Td>
                        <Td>{roleLabel(u.role)}</Td>
                        <Td>
                          {u.is_active ? <Badge tone="ok">active</Badge> : <Badge>disabled</Badge>} {u.locked && <Badge tone="bad">locked</Badge>}
                          {u.must_change_password && <Badge tone="warn">must change password</Badge>}
                        </Td>
                        <Td>{u.mfa_enabled ? <Badge tone="ok">on</Badge> : <span className="text-xs text-muted">off</span>}</Td>
                        <Td className="text-xs">{relTime(u.last_login_at)}{u.last_login_ip && <span className="text-muted"> · {u.last_login_ip}</span>}</Td>
                        <Td className="whitespace-nowrap text-right">
                          <Button size="sm" variant="ghost" onClick={() => setAct(u)}>Activity</Button>
                          {u.manageable && can("user.manage") && (
                            <>
                              <Button size="sm" variant="ghost" onClick={() => setEdit(u)}>Edit</Button>
                              {u.locked && <Button size="sm" variant="ghost" onClick={() => action(u, "unlock", "Account unlocked")}>Unlock</Button>}
                              <Button size="sm" variant="ghost" onClick={() => setPw(u)}>Set password</Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={async () => {
                                  try {
                                    const r = await api<{ reset_path: string; expires_in_hours: number }>(`/users/${u.id}/reset-token`, { method: "POST" });
                                    setToken({ user: u.username, path: r.reset_path, hours: r.expires_in_hours });
                                  } catch (e) {
                                    toast("bad", errorMessage(e));
                                  }
                                }}
                              >
                                Reset link
                              </Button>
                              {u.mfa_enabled && <Button size="sm" variant="ghost" onClick={() => action(u, "mfa-reset", "Two-factor authentication reset")}>Reset 2FA</Button>}
                              <Button size="sm" variant="ghost" onClick={() => setDel(u)}>Delete</Button>
                            </>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Pagination page={page} pageSize={50} total={d.total} onPage={setPage} />
              </>
            )
          }
        </Loadable>
      </Card>
      {edit && roles.data && <UserEditor initial={edit} roles={roles.data} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); toast("ok", "User saved"); mutate(); }} />}
      {pw && <SetPassword user={pw} onClose={() => { setPw(null); mutate(); }} />}
      {act && <Activity user={act} onClose={() => setAct(null)} />}
      <Modal open={!!token} title={`Password reset link for ${token?.user}`} onClose={() => setToken(null)}>
        {token && (
          <div className="space-y-3 text-sm">
            <Notice tone="warn">This link is shown once and works for {token.hours} hours. Give it to the user through a trusted channel.</Notice>
            <code className="block break-all rounded bg-panel-2 p-2 text-xs">{typeof window !== "undefined" ? window.location.origin : ""}{token.path}</code>
            <Button size="sm" onClick={() => navigator.clipboard?.writeText(`${window.location.origin}${token.path}`).then(() => toast("ok", "Copied"))}>Copy link</Button>
          </div>
        )}
      </Modal>
      <ConfirmDialog
        open={!!del}
        onClose={() => setDel(null)}
        danger
        title="Delete user"
        typeToConfirm={del?.username}
        confirmLabel="Delete user"
        message={<>The account <strong>{del?.username}</strong> will be deleted and its sessions ended. Its audit history is kept.</>}
        onConfirm={async () => {
          await api(`/users/${del!.id}`, { method: "DELETE" });
          toast("ok", "User deleted");
          mutate();
        }}
      />
    </div>
  );
}
