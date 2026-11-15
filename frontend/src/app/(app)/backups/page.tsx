"use client";

import { Download } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ChangeDialog, type ChangeRequest } from "@/components/ChangeDialog";
import { Badge, Button, Card, Empty, ErrorBox, Loadable, Modal, Notice, PageHeader, Pagination, Select, StatusBadge, Table, Tabs, Td, Th, useToast } from "@/components/ui";
import { api, buildUrl, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes, fmtDate, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Backup, Page, SwitchRow } from "@/lib/types";

interface Drift {
  id: number;
  switch_id: number;
  hostname: string;
  from_backup_id: number;
  to_backup_id: number;
  added: number;
  removed: number;
  expected: boolean;
  created_at: string;
}

function DiffView({ text }: { text: string }) {
  if (!text.trim()) return <Empty>The configurations are identical.</Empty>;
  return (
    <pre className="max-h-[60vh] overflow-auto rounded bg-panel-2 p-3 font-mono text-xs leading-5">
      {text.split("\n").map((l, i) => (
        <div
          key={i}
          className={
            l.startsWith("+++") || l.startsWith("---")
              ? "text-muted"
              : l.startsWith("+")
                ? "bg-ok/10 text-ok"
                : l.startsWith("-")
                  ? "bg-bad/10 text-bad"
                  : l.startsWith("@@")
                    ? "text-info"
                    : ""
          }
        >
          {l || " "}
        </div>
      ))}
    </pre>
  );
}

function ContentModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { can } = useAuth();
  const meta = useApi<Backup>(id ? `/backups/${id}` : null);
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    setText(null);
    setErr(null);
    if (id && can("backup.export")) api<string>(`/backups/${id}/content`, { raw: true }).then(setText).catch(setErr);
  }, [id, can]);
  if (!id) return null;
  return (
    <Modal open wide title={`Backup #${id}${meta.data?.hostname ? ` – ${meta.data.hostname}` : ""}`} onClose={onClose}>
      <div className="space-y-3">
        {meta.data && (
          <div className="flex flex-wrap gap-2 text-xs text-muted">
            <span>{fmtDate(meta.data.created_at)}</span>
            <StatusBadge status={meta.data.verify_status} />
            <span>{fmtBytes(meta.data.size_bytes)}</span>
            <span className="font-mono">sha256 {meta.data.sha256.slice(0, 16)}…</span>
            {meta.data.source === "simulator" && <Badge tone="sim">SIMULATED</Badge>}
          </div>
        )}
        {!can("backup.export") ? (
          <Notice tone="info">Your role can see backup metadata but not configuration contents.</Notice>
        ) : (
          <>
            <ErrorBox error={err} />
            {text === null && !err ? <p className="text-sm text-muted">Decrypting…</p> : <pre className="max-h-[60vh] overflow-auto rounded bg-panel-2 p-3 font-mono text-xs">{text}</pre>}
          </>
        )}
      </div>
    </Modal>
  );
}

function BackupsTab({ initialSwitch }: { initialSwitch: string }) {
  const { can } = useAuth();
  const toast = useToast();
  const [switchId, setSwitchId] = useState(initialSwitch);
  const [page, setPage] = useState(1);
  const [pick, setPick] = useState<number[]>([]);
  const [diff, setDiff] = useState<{ diff: string; added: number; removed: number } | null>(null);
  const [view, setView] = useState<number | null>(null);
  const [change, setChange] = useState<ChangeRequest | null>(null);
  const sw = useApi<Page<SwitchRow>>("/switches", { page_size: 500 });
  const { data, error, mutate } = useApi<Page<Backup>>("/backups", { switch_id: switchId, page, page_size: 50 });

  const verify = async (b: Backup) => {
    try {
      const r = await api<Backup>(`/backups/${b.id}/verify`, { method: "POST" });
      toast(r.verify_status === "verified" ? "ok" : "bad", `Backup #${b.id}: ${r.verify_status}`);
      mutate();
    } catch (e) {
      toast("bad", errorMessage(e));
    }
  };
  const compare = async () => {
    try {
      const [a, b] = [...pick].sort((x, y) => x - y);
      setDiff(await api(`/backups/diff`, { query: { a, b } }));
    } catch (e) {
      toast("bad", errorMessage(e));
    }
  };

  return (
    <Card bodyClassName="p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <Select aria-label="Switch" className="w-64" value={switchId} onChange={(e) => { setSwitchId(e.target.value); setPage(1); setPick([]); }}>
          <option value="">All switches</option>
          {sw.data?.items.map((s) => <option key={s.id} value={s.id}>{s.hostname}</option>)}
        </Select>
        {can("backup.export") && (
          <Button size="sm" disabled={pick.length !== 2} onClick={compare}>
            Compare selected ({pick.length}/2)
          </Button>
        )}
      </div>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) =>
          d.items.length === 0 ? (
            <Empty>No backups. Use “Back up now” on a switch or schedule backups in Settings.</Empty>
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    {can("backup.export") && <Th className="w-8" />}
                    <Th>#</Th>
                    <Th>Switch</Th>
                    <Th>Taken</Th>
                    <Th>Trigger</Th>
                    <Th>Size</Th>
                    <Th>Integrity</Th>
                    <Th>Restore tested</Th>
                    <Th>Note</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((b) => (
                    <tr key={b.id}>
                      {can("backup.export") && (
                        <Td>
                          <input
                            type="checkbox"
                            aria-label={`Select backup ${b.id} for comparison`}
                            checked={pick.includes(b.id)}
                            onChange={() => setPick((p) => (p.includes(b.id) ? p.filter((x) => x !== b.id) : [...p, b.id].slice(-2)))}
                          />
                        </Td>
                      )}
                      <Td className="tabular">{b.id}</Td>
                      <Td>
                        <Link href={`/switches/${b.switch_id}?tab=configuration`} className="hover:text-accent">{b.hostname}</Link>
                        {b.source === "simulator" && <> <Badge tone="sim">SIMULATED</Badge></>}
                      </Td>
                      <Td className="whitespace-nowrap text-xs">{fmtDate(b.created_at)}</Td>
                      <Td className="text-xs">{b.trigger}{b.job_id && <> · <Link href={`/changes/${b.job_id}`} className="text-accent">job #{b.job_id}</Link></>}</Td>
                      <Td className="tabular text-xs">{fmtBytes(b.size_bytes)}</Td>
                      <Td><StatusBadge status={b.verify_status} /></Td>
                      <Td>{b.restore_tested ? <Badge tone="ok" >yes</Badge> : <span className="text-xs text-muted">no</span>}</Td>
                      <Td className="max-w-40 truncate text-xs">{b.note}</Td>
                      <Td className="whitespace-nowrap text-right">
                        <Button size="sm" variant="ghost" onClick={() => setView(b.id)}>View</Button>
                        {can("backup.export") && (
                          <a className="inline-flex h-7 items-center px-2 text-xs hover:text-accent" href={buildUrl(`/backups/${b.id}/content`, { download: true })} aria-label={`Download backup ${b.id}`}>
                            <Download className="h-4 w-4" />
                          </a>
                        )}
                        {can("backup.manage") && <Button size="sm" variant="ghost" onClick={() => verify(b)}>Verify</Button>}
                        {can("config.restore") && b.verify_status === "verified" && (
                          <Button size="sm" variant="ghost" onClick={() => setChange({ operation: "config_restore", switchIds: [b.switch_id], params: { backup_id: b.id }, lockedParams: ["backup_id"], title: `Restore backup #${b.id} to ${b.hostname}` })}>
                            Restore…
                          </Button>
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
      <Modal open={!!diff} wide title={`Compare backups #${[...pick].sort((a, b) => a - b).join(" → #")}`} onClose={() => setDiff(null)}>
        {diff && (
          <div className="space-y-2">
            <p className="text-sm">
              <span className="text-ok">+{diff.added}</span> / <span className="text-bad">−{diff.removed}</span> lines
            </p>
            <DiffView text={diff.diff} />
          </div>
        )}
      </Modal>
      <ContentModal id={view} onClose={() => setView(null)} />
      <ChangeDialog request={change} onClose={() => setChange(null)} />
    </Card>
  );
}

function DriftTab() {
  const { can } = useAuth();
  const toast = useToast();
  const { data, error, mutate } = useApi<Drift[]>("/backups/drift");
  const [diff, setDiff] = useState<{ title: string; diff: string } | null>(null);
  const show = async (d: Drift) => {
    try {
      const r = await api<{ diff: string }>("/backups/diff", { query: { a: d.from_backup_id, b: d.to_backup_id } });
      setDiff({ title: `${d.hostname}: backup #${d.from_backup_id} → #${d.to_backup_id}`, diff: r.diff });
    } catch (e) {
      toast("bad", errorMessage(e));
    }
  };
  return (
    <Card bodyClassName="p-0">
      <p className="px-4 pt-3 text-xs text-muted">
        Configuration changes detected between consecutive backups. Changes made through this application are marked expected; anything else was changed outside
        the application.
      </p>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No configuration changes detected.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Detected</Th>
                  <Th>Switch</Th>
                  <Th>Change</Th>
                  <Th>Origin</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <Td className="whitespace-nowrap text-xs">{relTime(d.created_at)}</Td>
                    <Td><Link href={`/switches/${d.switch_id}?tab=configuration`} className="hover:text-accent">{d.hostname}</Link></Td>
                    <Td className="tabular text-xs"><span className="text-ok">+{d.added}</span> / <span className="text-bad">−{d.removed}</span></Td>
                    <Td>{d.expected ? <Badge tone="ok">via this application</Badge> : <Badge tone="warn">outside the application</Badge>}</Td>
                    <Td className="text-right">{can("backup.export") && <Button size="sm" variant="ghost" onClick={() => show(d)}>Show diff</Button>}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )
        }
      </Loadable>
      <Modal open={!!diff} wide title={diff?.title || ""} onClose={() => setDiff(null)}>
        {diff && <DiffView text={diff.diff} />}
      </Modal>
    </Card>
  );
}

function BackupsPage() {
  const params = useSearchParams();
  const [tab, setTab] = useState<"backups" | "drift">("backups");
  const [view, setView] = useState<number | null>(params.get("view") ? Number(params.get("view")) : null);
  return (
    <div>
      <PageHeader title="Configuration backups" subtitle="Encrypted, integrity-checked backups of switch running configurations" />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "backups", label: "Backups" }, { id: "drift", label: "Configuration drift" }]} />
      {tab === "backups" ? <BackupsTab initialSwitch={params.get("switch_id") || ""} /> : <DriftTab />}
      <ContentModal id={view} onClose={() => setView(null)} />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <BackupsPage />
    </Suspense>
  );
}
