"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthCard } from "@/components/AuthCard";
import { Button, ErrorBox, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";

function ResetForm() {
  const params = useSearchParams();
  const [token, setToken] = useState(params.get("token") || "");
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw !== confirm) {
      setErr(new Error("The passwords do not match"));
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api("/auth/reset", { method: "POST", body: { token, new_password: pw } });
      setDone(true);
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title="Reset password">
      {done ? (
        <div className="space-y-3">
          <Notice tone="info">Your password was changed. All your other sessions were signed out.</Notice>
          <Link href="/login" className="block text-center text-accent underline">
            Sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <Field label="Reset token" htmlFor="token" hint="Provided by your administrator. Tokens expire and work once.">
            <Input id="token" value={token} onChange={(e) => setToken(e.target.value)} required autoComplete="off" />
          </Field>
          <Field label="New password" htmlFor="pw" hint="At least 12 characters with three of: lowercase, uppercase, digits, symbols.">
            <Input id="pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required minLength={12} />
          </Field>
          <Field label="Confirm new password" htmlFor="pw2">
            <Input id="pw2" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </Field>
          <ErrorBox error={err} />
          <Button type="submit" variant="primary" loading={busy} className="w-full">
            Set new password
          </Button>
          <Link href="/login" className="block text-center text-sm text-muted underline">
            Back to sign in
          </Link>
        </form>
      )}
    </AuthCard>
  );
}

export default function ResetPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
