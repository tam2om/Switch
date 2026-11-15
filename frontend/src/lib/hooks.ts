"use client";

import useSWR, { type SWRConfiguration } from "swr";
import { api, buildUrl, type ApiError } from "./api";
import { useAuth } from "./auth";

type Query = Record<string, string | number | boolean | null | undefined>;

/** GET an API path with SWR. Pass null to skip. `live` refreshes at the user's dashboard interval. */
export function useApi<T>(path: string | null, query?: Query, opts: SWRConfiguration & { live?: boolean } = {}) {
  const { refreshMs } = useAuth();
  const key = path ? buildUrl(path, query) : null;
  const { live, ...rest } = opts;
  return useSWR<T, ApiError>(key, (k: string) => api<T>(k), {
    refreshInterval: live ? refreshMs : 0,
    revalidateOnFocus: false,
    keepPreviousData: true,
    ...rest,
  });
}
