import { Credit, Logo } from "./Credit";

export function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-4">
      <div className="w-full max-w-sm rounded-lg border border-line bg-panel p-6 shadow-xl">
        <div className="mb-5 flex items-center gap-2">
          <Logo size={28} />
          <div>
            <div className="text-sm text-muted">Aruba Network Manager</div>
            <h1 className="text-lg font-semibold">{title}</h1>
          </div>
        </div>
        {children}
        <p className="mt-6 text-center text-xs text-muted">Authorised personnel only. All activity is audited.</p>
      </div>
      <Credit className="max-w-sm" />
    </div>
  );
}
