"use client";

import { Download, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Empty, Input, Loadable, Modal, Notice, PageHeader, Pagination, Select, Table, Td, Th, useToast } from "@/components/ui";
import { api, buildUrl, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AuditRow, Page } from "@/lib/types";

export default function AuditPage() {
  const { can } = useAuth();
  const toast = useToast();
  const all = can("audit.view_all");
  const [category, setCategory] = useState("");
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<AuditRow | null>(null);
  const [verify, setVerify] = useState<{ valid: boolean; checked: number; broken_at?: number; reason?: string } | null>(null);
  const { data, error, mutate } = useApi<Page<AuditRow>>("/audit", {
    category,
    action,
    actor,
    since: since ? new Date(since).toISOString() : "",
    until: until ? new Date(until).toISOString() : "",
    page,
    page_size: 100,
  });
  const reset = () => setPage(1);

  return (
    <div>
      <PageHeader
        title="Audit log"
        subtitle={all ? "Append-only, hash-chained record of every security and operational action" : "Operational actions (your role cannot see security events)"}
        actions={
          all && (
            <>
              <Button
                onClick={async () => {
                  try {
                    setVerify(await api("/audit/verify"));
                  } catch (e) {
                    toast("bad", errorMessage(e));
                  }
                }}
              >
                <ShieldCheck className="h-4 w-4" /> Verify integrity
              </Button>
              <a href={buildUrl("/audit/export")} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-panel-2 px-3 text-sm hover:bg-line" download>
                <Download className="h-4 w-4" /> Export CSV
              </a>
            </>
          )
        }
      />
      {verify && (
        <div className="mb-4">
          <Notice tone={verify.valid ? "info" : "bad"}>
            {verify.valid
              ? `Integrity verified: ${verify.checked} entries, hash chain intact.`
              : `Integrity check FAILED at entry ${verify.broken_at ?? "?"}: ${verify.reason ?? "hash mismatch"}. The audit log may have been tampered with.`}
          </Notice>
        </div>
      )}
      <Card bodyClassName="p-0">
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          {all && (
            <Select aria-label="Category" className="w-40" value={category} onChange={(e) => { setCategory(e.target.value); reset(); }}>
              <option value="">All categories</option>
              <option value="security">Security</option>
              <option value="auth">Authentication</option>
              <option value="operational">Operational</option>
            </Select>
          )}
          <Input className="w-48" placeholder="Action prefix, e.g. job." aria-label="Action" value={action} onChange={(e) => { setAction(e.target.value); reset(); }} />
          <Input className="w-40" placeholder="Username" aria-label="Actor" value={actor} onChange={(e) => { setActor(e.target.value); reset(); }} />
          <Input className="w-52" type="datetime-local" aria-label="From" value={since} onChange={(e) => { setSince(e.target.value); reset(); }} />
          <Input className="w-52" type="datetime-local" aria-label="Until" value={until} onChange={(e) => { setUntil(e.target.value); reset(); }} />
        </div>
        <Loadable data={data} error={error} retry={() => mutate()}>
          {(d) =>
            d.items.length === 0 ? (
              <Empty>No entries.</Empty>
            ) : (
              <>
                <Table>
                  <thead>
                    <tr>
                      <Th>Time</Th>
                      <Th>Category</Th>
                      <Th>Action</Th>
                      <Th>Result</Th>
                      <Th>Actor</Th>
                      <Th>Target</Th>
                      <Th>Source IP</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((r) => (
                      <tr key={r.id}>
                        <Td className="whitespace-nowrap text-xs">{fmtDate(r.ts)}</Td>
                        <Td><Badge>{r.category}</Badge></Td>
                        <Td className="font-mono text-xs">{r.action}</Td>
                        <Td><Badge tone={r.result === "success" ? "ok" : "bad"}>{r.result}</Badge></Td>
                        <Td>{r.actor || "–"}</Td>
                        <Td className="text-xs">{r.target_type ? `${r.target_type} ${r.target_id ?? ""}` : "–"}</Td>
                        <Td className="font-mono text-xs">{r.ip || "–"}</Td>
                        <Td className="text-right">{Object.keys(r.details || {}).length > 0 && <Button size="sm" variant="ghost" onClick={() => setDetail(r)}>Details</Button>}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Pagination page={page} pageSize={100} total={d.total} onPage={setPage} />
              </>
            )
          }
        </Loadable>
      </Card>
      <Modal open={!!detail} wide title={`Audit entry #${detail?.id}`} onClose={() => setDetail(null)}>
        <pre className="overflow-auto rounded bg-panel-2 p-3 text-xs">{JSON.stringify(detail?.details, null, 2)}</pre>
        <p className="mt-2 text-xs text-muted">Secrets are redacted before they are written to the audit log.</p>
      </Modal>
    </div>
  );
}
