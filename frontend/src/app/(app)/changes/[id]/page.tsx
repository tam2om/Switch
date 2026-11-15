"use client";

import { ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, ErrorBox, Field, KV, Loadable, Modal, Notice, RiskBadge, StatusBadge, Table, Td, Textarea, Th, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Job, JobResult } from "@/lib/types";

const ACTIVE = new Set(["queued", "running"]);

function Steps({ r }: { r: JobResult }) {
  const steps = r.details?.steps || [];
  if (!steps.length) return <span className="text-xs text-muted">–</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {steps.map((s, i) => (
        <span key={i} title={JSON.stringify(s)} className={`inline-flex items-center gap-0.5 rounded border px-1 text-[11px] ${s.ok ? "border-ok/40 text-ok" : "border-bad/40 text-bad"}`}>
          {s.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
          {s.step}
        </span>
      ))}
    </div>
  );
}

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { can, me } = useAuth();
  const { data, error, mutate } = useApi<Job>(`/jobs/${id}`, undefined, {
    refreshInterval: (d) => (d && (ACTIVE.has(d.status) || d.cancel_requested) ? 2000 : 0),
  });
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const act = async (path: string, body?: unknown) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<Job>(`/jobs/${id}/${path}`, { method: "POST", body });
      return r;
    } catch (e) {
      setErr(e);
      toast("bad", errorMessage(e));
      return null;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <Link href="/changes" className="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="h-4 w-4" /> Changes
      </Link>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(j) => {
          const results = j.results || [];
          const failed = (j.progress.failed || 0) + (j.progress.verify_failed || 0);
          const ownJob = me?.id === j.requested_by_id;
          return (
            <div className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold">
                    #{j.id} {j.title} <StatusBadge status={j.status} /> <RiskBadge risk={j.risk} />
                  </h1>
                  <p className="text-sm text-muted">
                    Requested by {j.requested_by} {relTime(j.created_at)} · {j.target_count} switch(es)
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {j.status === "pending_approval" && can("change.approve") && (
                    <>
                      <Button variant="primary" onClick={() => setDecision("approve")} title={ownJob ? "Approving your own change may be blocked by the four-eyes policy" : undefined}>
                        Approve
                      </Button>
                      <Button variant="danger" onClick={() => setDecision("reject")}>Reject</Button>
                    </>
                  )}
                  {(j.status === "pending_approval" || ACTIVE.has(j.status)) && !j.cancel_requested && (
                    <Button onClick={async () => { if (await act("cancel")) { toast("ok", "Cancellation requested"); mutate(); } }} loading={busy}>
                      {j.status === "running" ? "Stop after current switch" : "Cancel"}
                    </Button>
                  )}
                  {(j.status === "failed" || j.status === "partial") && failed > 0 && (
                    <Button
                      onClick={async () => {
                        const r = await act("retry");
                        if (r) router.push(`/changes/${r.id}`);
                      }}
                      loading={busy}
                    >
                      Retry failed switches
                    </Button>
                  )}
                </div>
              </div>
              <ErrorBox error={err} />
              {j.status === "pending_approval" && (
                <Notice tone="warn">
                  This change is waiting for approval from {can("change.approve") ? "another" : "a Super"} administrator. It has not touched any switch yet.
                </Notice>
              )}
              {j.cancel_requested && ACTIVE.has(j.status) && <Notice tone="warn">Cancellation requested. The job stops before the next switch.</Notice>}
              {j.summary?.stopped_reason && <Notice tone="bad">Stopped: {j.summary.stopped_reason}</Notice>}
              {j.error && <Notice tone="bad">{j.error}</Notice>}

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                <Card title="Details" className="xl:col-span-2">
                  <KV
                    items={[
                      ["Operation", j.operation],
                      ["Batch size", j.batch_size],
                      ["Canary first", j.canary ? "yes" : "no"],
                      ["Stop after failures", j.max_failures],
                      ["Created", fmtDate(j.created_at)],
                      ["Started", fmtDate(j.started_at)],
                      ["Finished", fmtDate(j.finished_at)],
                      ["Needs approval", j.requires_approval ? "yes" : "no"],
                    ]}
                  />
                  <div className="mt-3">
                    <div className="mb-1 text-xs font-medium text-muted">Parameters</div>
                    <pre className="overflow-x-auto rounded bg-panel-2 p-2 text-xs">{JSON.stringify(j.params, null, 2)}</pre>
                  </div>
                  {j.risk_reasons.length > 0 && (
                    <ul className="mt-3 list-inside list-disc text-sm text-muted">
                      {j.risk_reasons.map((r, i) => <li key={i}>{r}</li>)}
                    </ul>
                  )}
                </Card>
                <Card title="Progress">
                  <div className="space-y-1 text-sm">
                    {Object.entries(j.progress).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span className="text-muted">{k.replace(/_/g, " ")}</span>
                        <span className={`tabular ${k.includes("fail") && v ? "text-bad" : ""}`}>{v}</span>
                      </div>
                    ))}
                  </div>
                  {j.approvals.length > 0 && (
                    <div className="mt-4 border-t border-line pt-3 text-sm">
                      <div className="mb-1 text-xs font-medium text-muted">Approvals</div>
                      {j.approvals.map((a, i) => (
                        <div key={i}>
                          <Badge tone={a.decision === "approved" ? "ok" : "bad"}>{a.decision}</Badge> {a.approver} <span className="text-xs text-muted">{relTime(a.created_at || a.at)}</span>
                          {a.comment && <p className="text-xs text-muted">“{a.comment}”</p>}
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </div>

              <Card title="Per-switch results" bodyClassName="p-0">
                <Table>
                  <thead>
                    <tr>
                      <Th>Batch</Th>
                      <Th>Switch</Th>
                      <Th>Status</Th>
                      <Th>Steps</Th>
                      <Th>Message</Th>
                      <Th>Pre-change backup</Th>
                      <Th>Finished</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r) => (
                      <tr key={r.id}>
                        <Td className="tabular">{r.batch_index + 1}</Td>
                        <Td><Link href={`/switches/${r.switch_id}`} className="hover:text-accent">{r.hostname || `#${r.switch_id}`}</Link></Td>
                        <Td><StatusBadge status={r.status} />{r.attempts > 1 && <span className="ml-1 text-xs text-muted">×{r.attempts}</span>}</Td>
                        <Td><Steps r={r} /></Td>
                        <Td className="max-w-96 text-xs">{r.message}</Td>
                        <Td className="text-xs">{r.pre_backup_id ? <Link href={`/backups?view=${r.pre_backup_id}`} className="text-accent">#{r.pre_backup_id}</Link> : "–"}</Td>
                        <Td className="whitespace-nowrap text-xs">{r.finished_at ? relTime(r.finished_at) : "–"}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>

              <Modal
                open={!!decision}
                onClose={() => setDecision(null)}
                title={decision === "approve" ? "Approve change" : "Reject change"}
                footer={
                  <>
                    <Button onClick={() => setDecision(null)}>Cancel</Button>
                    <Button
                      variant={decision === "approve" ? "primary" : "danger"}
                      loading={busy}
                      onClick={async () => {
                        const r = await act(decision!, { comment });
                        if (r) {
                          setDecision(null);
                          setComment("");
                          toast("ok", decision === "approve" ? "Change approved and queued" : "Change rejected");
                          mutate();
                        }
                      }}
                    >
                      {decision === "approve" ? "Approve and run" : "Reject"}
                    </Button>
                  </>
                }
              >
                <div className="space-y-3 text-sm">
                  <p>
                    <RiskBadge risk={j.risk} /> {j.title} on {j.target_count} switch(es).
                  </p>
                  <Field label="Comment" htmlFor="dec-comment">
                    <Textarea id="dec-comment" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
                  </Field>
                  <ErrorBox error={err} />
                </div>
              </Modal>
            </div>
          );
        }}
      </Loadable>
    </div>
  );
}
