"use client";

import { SWRConfig } from "swr";
import { ToastProvider } from "@/components/ui";
import { AuthProvider } from "@/lib/auth";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ errorRetryCount: 2 }}>
      <AuthProvider>
        <ToastProvider>{children}</ToastProvider>
      </AuthProvider>
    </SWRConfig>
  );
}
