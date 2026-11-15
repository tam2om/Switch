import { cx } from "@/components/ui";

export const CREDIT_TEXT = "Developed in-house by the AMCO Information Technology Department, 2026.";

export function Credit({ className }: { className?: string }) {
  return <footer className={cx("text-center text-xs text-muted", className)}>{CREDIT_TEXT}</footer>;
}

export function Logo({ size = 24 }: { size?: number }) {
  // eslint-disable-next-line @next/next/no-img-element -- static same-origin icon, no optimisation needed
  return <img src="/icon-192.png" alt="" width={size} height={size} className="shrink-0" aria-hidden />;
}
