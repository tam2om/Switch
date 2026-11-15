import { Badge } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import type { SwitchRow } from "@/lib/types";

/** Hardware validation state of a switch's model, from stored read-only harness evidence. */
export function HardwareBadge({ sw, compact = false }: { sw: SwitchRow; compact?: boolean }) {
  if (!sw.product_number || sw.is_simulated || sw.model_verified) return null;
  const ev = sw.hardware_evidence;
  if (ev?.read_checks_passed) {
    const title = `Read-only hardware checks: ${ev.passed} of ${ev.passed + ev.failed} passed on ${ev.hostname} (${ev.firmware}), ${fmtDate(ev.at)}. Change operations count as verified once a job has applied and read them back on this model (Administration > Inventory).`;
    return compact ? (
      <div className="text-ok" title={title}>validated on hardware (read-only)</div>
    ) : (
      <Badge tone="ok" title={title}>validated on hardware (read-only)</Badge>
    );
  }
  if (ev) {
    const text = `hardware checks ${ev.passed}/${ev.passed + ev.failed} passed`;
    const title = `Read-only hardware checks on ${ev.hostname} (${ev.firmware}), ${fmtDate(ev.at)}: ${ev.failed} failed. Fix the cause and run the validation again.`;
    return compact ? <div className="text-warn" title={title}>{text}</div> : <Badge tone="warn" title={title}>{text}</Badge>;
  }
  return compact ? (
    <div className="text-muted">hardware not validated</div>
  ) : (
    <Badge tone="warn" title="Not yet validated on physical hardware">hardware validation pending</Badge>
  );
}
