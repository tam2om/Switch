"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useSWRConfig } from "swr";
import { AuthCard } from "@/components/AuthCard";
import { Button, ErrorBox, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";

interface LoginResp {
  mfa_required: boolean;
  user: { must_change_password: boolean };
}

function safeNext(n: string | null): string {
  return n && n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/login") ? n : "/";
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const { mutate } = useSWRConfig();
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [setup, setSetup] = useState<{ initialized: boolean } | null>(null);

  useEffect(() => {
    api<{ initialized: boolean }>("/setup/status").then(setSetup).catch(() => undefined);
  }, []);

  const finish = async (mustChange: boolean) => {
    await mutate("/auth/me");
    router.replace(mustChange ? "/change-password" : next);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      if (step === "password") {
        const r = await api<LoginResp>("/auth/login", { method: "POST", body: { username, password } });
        setPassword("");
        if (r.mfa_required) setStep("mfa");
        else await finish(r.user.must_change_password);
      } else {
        const r = await api<{ user: { must_change_password: boolean } }>("/auth/mfa/verify", { method: "POST", body: { code } });
        await finish(r.user?.must_change_password ?? false);
      }
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title={step === "password" ? "Sign in" : "Two-factor verification"}>
      {setup && !setup.initialized && (
        <div className="mb-4">
          <Notice tone="warn">
            No administrator exists yet. Create the first Super Admin on the server with
            <code className="mx-1 rounded bg-panel-2 px-1">python -m app.cli create-superadmin &lt;username&gt;</code>
            (see the deployment guide).
          </Notice>
        </div>
      )}
      <form onSubmit={submit} className="space-y-3">
        {step === "password" ? (
          <>
            <Field label="Username" htmlFor="username">
              <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            </Field>
            <Field label="Password" htmlFor="password">
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
          </>
        ) : (
          <Field label="Authentication code" htmlFor="code" hint="Enter the 6-digit code from your authenticator app.">
            <Input id="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
          </Field>
        )}
        <ErrorBox error={err} />
        <Button type="submit" variant="primary" loading={busy} className="w-full">
          {step === "password" ? "Sign in" : "Verify"}
        </Button>
      </form>
      <p className="mt-4 text-xs text-muted">
        Forgot your password? Ask an administrator for a one-time reset link, then open it to{" "}
        <a href="/reset-password" className="text-accent underline">set a new password</a>.
      </p>
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
