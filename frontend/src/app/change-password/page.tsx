"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthCard } from "@/components/AuthCard";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

import { PASSWORD_HINT } from "@/lib/format";

export default function ChangePasswordPage() {
  const router = useRouter();
  const { me, refresh, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next !== confirm) {
      setErr(new Error("The new passwords do not match"));
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api("/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      await refresh();
      router.replace("/");
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title="Change password">
      {me?.must_change_password && <p className="mb-3 text-sm text-warn">You must set a new password before continuing.</p>}
      <form onSubmit={submit} className="space-y-3">
        <Field label="Current password" htmlFor="cur">
          <Input id="cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </Field>
        <Field label="New password" htmlFor="new" hint={PASSWORD_HINT}>
          <Input id="new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={12} />
        </Field>
        <Field label="Confirm new password" htmlFor="conf">
          <Input id="conf" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </Field>
        <ErrorBox error={err} />
        <Button type="submit" variant="primary" loading={busy} className="w-full">
          Change password
        </Button>
        <Button variant="ghost" className="w-full" onClick={logout}>
          Sign out
        </Button>
      </form>
    </AuthCard>
  );
}
