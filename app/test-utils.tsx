import type { ReactElement } from "react";
import { act, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(ui: ReactElement, client?: QueryClient) {
  const queryClient = client ?? makeTestQueryClient();
  const wrap = (node: ReactElement) => (
    <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>
  );
  const utils = render(wrap(ui));
  return {
    ...utils,
    // RTL's bare rerender drops the provider; wrap it
    rerender: (next: ReactElement) => utils.rerender(wrap(next)),
    queryClient,
  };
}

export const settled = () => act(async () => {});

export function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
