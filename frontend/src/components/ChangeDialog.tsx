"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import type { Job, Operation, Preview } from "@/lib/types";
import { defaultsFor, SchemaForm, type Values } from "./SchemaForm";
import { Badge, Button, Checkbox, ErrorBox, Field, Input, Modal, Notice, RiskBadge, SimBadge, Spinner, useToast } from "./ui";

export interface ChangeRequest {
  operation: string;
  switchIds: number[];
  params?: Values;
  /** Parameters fixed by the calling screen (e.g. the selected ports) that the user should not edit here. */
  lockedParams?: string[];
  title?: string;
  /** Apply a saved template: the server merges its stored (possibly secret) parameters. */
  templateId?: number;
}

const MASK = "********";

/** Hook to the shared change workflow: edit parameters → server-side risk preview → submit job. */
export function ChangeDialog({
  request,
  onClose,
  onCreated,
}: {
  request: ChangeRequest | null;
  onClose: () => void;
  onCreated?: (job: Job) => void;
}) {
  const { mode } = useAuth();
  const toast = useToast();
  const { data: ops } = useApi<Operation[]>(request ? "/operations" : null);
  const op = useMemo(() => ops?.find((o) => o.name === request?.operation), [ops, request?.operation]);
  const [values, setValues] = useState<Values>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [created, setCreated] = useState<Job | null>(null);
  const [batch, setBatch] = useState<string>("");
  const [canary, setCanary] = useState(true);
  const [maxFailures, setMaxFailures] = useState("1");

  useEffect(() => {
    if (!request || !op) return;
    setValues({ ...defaultsFor(op.schema), ...(request.params || {}) });
    setPreview(null);
    setAck(false);
    setErr(null);
    setCreated(null);
    setBatch("");
    setCanary(true);
    setMaxFailures("1");
  }, [request, op]);

  const body = () => ({
    operation: request!.operation,
    params: values,
    switch_ids: request!.switchIds,
    batch_size: batch ? parseInt(batch, 10) : null,
    canary,
    max_failures: parseInt(maxFailures || "1", 10),
    acknowledge_risk: ack,
  });

  const doPreview = async () => {
    setBusy(true);
    setErr(null);
    try {
      setPreview(await api<Preview>("/jobs/preview", { method: "POST", body: body() }));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      let job: Job;
      if (request!.templateId) {
        // Masked secrets stay on the server; only send parameters the user actually changed.
        const params = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== MASK));
        job = await api<Job>(`/templates/${request!.templateId}/apply`, { method: "POST", body: { ...body(), params } });
      } else {
        job = await api<Job>("/jobs", { method: "POST", body: body() });
      }
      setCreated(job);
      toast("ok", job.status === "pending_approval" ? `Change #${job.id} submitted for approval` : `Change #${job.id} queued`);
      onCreated?.(job);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  if (!request) return null;
  const title = request.title || op?.title || "Change";
  const multi = request.switchIds.length > 1;

  let footer: React.ReactNode;
  if (created) {
    footer = (
      <>
        <Button onClick={onClose}>Close</Button>
        <Link href={`/changes/${created.id}`} className="inline-flex h-9 items-center rounded-md bg-accent px-3 text-sm font-medium text-accent-fg">
          Open change #{created.id}
        </Link>
      </>
    );
  } else if (preview) {
    footer = (
      <>
        <Button onClick={() => setPreview(null)}>Back</Button>
        <Button
          variant={preview.risk === "critical" || preview.risk === "high" ? "danger" : "primary"}
          loading={busy}
          disabled={preview.requires_acknowledgement && !ack}
          onClick={submit}
        >
          {preview.requires_approval ? "Submit for approval" : "Apply change"}
        </Button>
      </>
    );
  } else {
    footer = (
      <>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!op || !op.allowed} onClick={doPreview}>
          Review impact
        </Button>
      </>
    );
  }

  return (
    <Modal open title={title} onClose={onClose} footer={footer} wide>
      {!op ? (
        ops ? <ErrorBox error={new Error(`Operation ${request.operation} is not available`)} /> : <Spinner />
      ) : created ? (
        <div className="space-y-2 text-sm">
          <p>
            Change <strong>#{created.id}</strong> was created with status <Badge>{created.status.replace(/_/g, " ")}</Badge>.
          </p>
          {created.status === "pending_approval" && (
            <p className="text-muted">A second administrator must approve it before it runs. You can follow it on the Changes page.</p>
          )}
        </div>
      ) : preview ? (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge risk={preview.risk} />
            <span className="font-medium">{preview.title}</span>
            <span className="text-muted">
              on {preview.switches.length} switch{preview.switches.length === 1 ? "" : "es"}
            </span>
          </div>
          {preview.warning && <Notice tone="warn">{preview.warning}</Notice>}
          <ul className="list-inside list-disc space-y-0.5 text-muted">
            {preview.takes_backup && <li>A verified configuration backup is taken on each switch before the change.</li>}
            <li>The result is read back from the switch to verify it, then saved to startup-config.</li>
            {preview.requires_approval ? (
              <li className="text-warn">This change needs approval from another administrator before it runs.</li>
            ) : (
              <li>The change runs immediately after you confirm.</li>
            )}
            {multi && <li>Switches are processed in batches{canary ? ", starting with a single canary switch" : ""}; the job stops after {maxFailures} failure(s).</li>}
          </ul>
          <div className="max-h-64 overflow-y-auto rounded border border-line">
            <table className="w-full text-sm">
              <tbody>
                {preview.switches.map((s) => (
                  <tr key={s.switch_id} className="border-b border-line/60 last:border-0">
                    <td className="whitespace-nowrap px-3 py-1.5 font-medium">
                      {s.hostname} <SimBadge show={s.simulated} />
                    </td>
                    <td className="px-3 py-1.5">
                      <RiskBadge risk={s.risk} />
                    </td>
                    <td className="px-3 py-1.5 text-muted">{s.reasons.join("; ") || "No specific risks detected"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.requires_acknowledgement && (
            <div className="rounded-md border border-bad/50 bg-bad/10 p-3">
              <div className="mb-2 flex items-center gap-2 font-medium text-bad">
                <ShieldAlert className="h-4 w-4" /> Critical change
              </div>
              <Checkbox
                checked={ack}
                onChange={setAck}
                label="I understand this change can interrupt connectivity or management access and I accept the risk."
              />
            </div>
          )}
          <ErrorBox error={err} />
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Target: {request.switchIds.length} switch{request.switchIds.length === 1 ? "" : "es"}.
            {op.warning && <span className="mt-1 block text-warn">{op.warning}</span>}
          </p>
          {!op.allowed && <Notice tone="bad">Your role is not permitted to run this operation.</Notice>}
          {request.lockedParams?.length ? (
            <div className="flex flex-wrap gap-2 text-sm">
              {request.lockedParams.map((k) => (
                <Badge key={k}>
                  {k}: {Array.isArray(values[k]) ? (values[k] as unknown[]).join(", ") : String(values[k])}
                </Badge>
              ))}
            </div>
          ) : null}
          <SchemaForm schema={op.schema} values={values} onChange={setValues} hidden={request.lockedParams} />
          {multi && mode === "pro" && (
            <div className="grid grid-cols-1 gap-3 border-t border-line pt-3 sm:grid-cols-3">
              <Field label="Batch size" hint="Empty = server default. High-risk changes always run one at a time.">
                <Input type="number" min={1} value={batch} onChange={(e) => setBatch(e.target.value)} />
              </Field>
              <Field label="Stop after failures">
                <Input type="number" min={1} value={maxFailures} onChange={(e) => setMaxFailures(e.target.value)} />
              </Field>
              <div className="pt-6">
                <Checkbox checked={canary} onChange={setCanary} label="Canary first" />
              </div>
            </div>
          )}
          <ErrorBox error={err} />
        </div>
      )}
    </Modal>
  );
}
