export function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-lg border border-line bg-panel p-6 shadow-xl">
        <div className="mb-5 flex items-center gap-2">
          <span className="inline-block h-7 w-7 rounded bg-accent" aria-hidden />
          <div>
            <div className="text-sm text-muted">Aruba Network Manager</div>
            <h1 className="text-lg font-semibold">{title}</h1>
          </div>
        </div>
        {children}
        <p className="mt-6 text-center text-xs text-muted">Authorised personnel only. All activity is audited.</p>
      </div>
    </div>
  );
}
