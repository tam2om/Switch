"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { roleLabel } from "@/components/AppShell";
import { Badge, Button, Card, ErrorBox, Field, Input, KV, Loadable, Notice, PageHeader, Select, Table, Td, Th, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, PASSWORD_HINT, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface SessionRow {
  id: number;
  ip: string;
  user_agent: string;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}

function PasswordCard() {
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [conf, setConf] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next !== conf) {
      setErr(new Error("The new passwords do not match"));
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api("/auth/password", { method: "POST", body: { current_password: cur, new_password: next } });
      setCur("");
      setNext("");
      setConf("");
      toast("ok", "Password changed. Your other sessions were signed out.");
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Change password">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Current password" htmlFor="p-cur"><Input id="p-cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
        <Field label="New password" htmlFor="p-new" hint={PASSWORD_HINT}><Input id="p-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required /></Field>
        <Field label="Confirm new password" htmlFor="p-conf"><Input id="p-conf" type="password" autoComplete="new-password" value={conf} onChange={(e) => setConf(e.target.value)} required /></Field>
        <ErrorBox error={err} />
        <Button type="submit" variant="primary" loading={busy}>Change password</Button>
      </form>
    </Card>
  );
}

function MfaCard() {
  const { me, refresh } = useAuth();
  const toast = useToast();
  const [enroll, setEnroll] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [qr, setQr] = useState<string>("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (enroll) QRCode.toDataURL(enroll.otpauth_uri, { margin: 1, width: 200 }).then(setQr).catch(() => setQr(""));
  }, [enroll]);
  if (!me) return null;
  return (
    <Card title="Two-factor authentication" actions={me.mfa_enabled ? <Badge tone="ok">enabled</Badge> : <Badge>off</Badge>}>
      {me.mfa_enabled ? (
        <p className="text-sm text-muted">Sign-in requires a code from your authenticator app. If you lose the device, ask an administrator to reset two-factor authentication for your account.</p>
      ) : !enroll ? (
        <div className="space-y-3 text-sm">
          {me.mfa_setup_required && <Notice tone="warn">Your role requires two-factor authentication. Set it up to continue using the application.</Notice>}
          <p className="text-muted">Use any TOTP authenticator app (for example Microsoft Authenticator, Google Authenticator or FreeOTP).</p>
          <ErrorBox error={err} />
          <Button
            variant="primary"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                setEnroll(await api("/auth/mfa/enroll", { method: "POST" }));
              } catch (e) {
                setErr(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            Set up two-factor authentication
          </Button>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <p>Scan the code with your authenticator app, or enter the key manually, then type the 6-digit code it shows.</p>
          {qr && <img src={qr} alt="Authenticator QR code" className="rounded bg-white p-1" width={200} height={200} />}
          <code className="block break-all rounded bg-panel-2 p-2 text-xs">{enroll.secret}</code>
          <Field label="Verification code" htmlFor="mfa-code">
            <Input id="mfa-code" className="w-40" inputMode="numeric" maxLength={6} autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
          <ErrorBox error={err} />
          <Button
            variant="primary"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await api("/auth/mfa/confirm", { method: "POST", body: { code } });
                toast("ok", "Two-factor authentication enabled");
                setEnroll(null);
                await refresh();
              } catch (e) {
                setErr(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            Confirm
          </Button>
        </div>
      )}
    </Card>
  );
}

function SessionsCard() {
  const toast = useToast();
  const { data, error, mutate } = useApi<SessionRow[]>("/auth/sessions");
  return (
    <Card
      title="Active sessions"
      bodyClassName="p-0"
      actions={
        <Button
          size="sm"
          onClick={async () => {
            try {
              await api("/auth/sessions/revoke-others", { method: "POST" });
              toast("ok", "Other sessions signed out");
              mutate();
            } catch (e) {
              toast("bad", errorMessage(e));
            }
          }}
        >
          Sign out other sessions
        </Button>
      }
    >
      <Loadable data={data} error={error}>
        {(rows) => (
          <Table>
            <thead><tr><Th>Started</Th><Th>Last active</Th><Th>IP</Th><Th>Browser</Th></tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <Td className="text-xs">{fmtDate(s.created_at)} {s.current && <Badge tone="accent">this session</Badge>}</Td>
                  <Td className="text-xs">{relTime(s.last_seen_at)}</Td>
                  <Td className="font-mono text-xs">{s.ip}</Td>
                  <Td className="max-w-72 truncate text-xs" >{s.user_agent}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Loadable>
    </Card>
  );
}

export default function ProfilePage() {
  const { me, theme, setTheme, mode, setMode, refresh } = useAuth();
  const toast = useToast();
  const [refreshSec, setRefreshSec] = useState(String(me?.preferences?.refresh_seconds || ""));
  if (!me) return null;
  return (
    <div className="space-y-4">
      <PageHeader title="My profile" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Account">
          <KV
            items={[
              ["Username", me.username],
              ["Name", me.full_name || "–"],
              ["Email", me.email || "–"],
              ["Role", roleLabel(me.role)],
              ["Last sign-in", `${fmtDate(me.last_login_at)}${me.last_login_ip ? ` from ${me.last_login_ip}` : ""}`],
            ]}
          />
        </Card>
        <Card title="Preferences">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Theme" htmlFor="pref-theme">
              <Select id="pref-theme" value={theme} onChange={(e) => setTheme(e.target.value as "dark" | "light")}>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </Select>
            </Field>
            <Field label="Interface mode" htmlFor="pref-mode" hint="Pro shows more columns and advanced actions.">
              <Select id="pref-mode" value={mode} onChange={(e) => setMode(e.target.value as "simple" | "pro")}>
                <option value="simple">Simple</option>
                <option value="pro">Pro</option>
              </Select>
            </Field>
            <Field label="Auto refresh (seconds)" htmlFor="pref-refresh" hint={`10–600. Default ${me.dashboard_refresh_seconds}.`}>
              <div className="flex gap-2">
                <Input id="pref-refresh" type="number" min={10} max={600} value={refreshSec} onChange={(e) => setRefreshSec(e.target.value)} />
                <Button
                  onClick={async () => {
                    try {
                      await api("/auth/preferences", { method: "PATCH", body: { refresh_seconds: refreshSec ? Number(refreshSec) : null } });
                      await refresh();
                      toast("ok", "Saved");
                    } catch (e) {
                      toast("bad", errorMessage(e));
                    }
                  }}
                >
                  Save
                </Button>
              </div>
            </Field>
          </div>
        </Card>
        <PasswordCard />
        <MfaCard />
      </div>
      <SessionsCard />
    </div>
  );
}
