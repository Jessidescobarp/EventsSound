import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Page } from "../api/records";
import { AuthProvider } from "../auth/AuthProvider";
import { usePagedRecords } from "./usePagedRecords";

const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>;
const page = (items: string[], total: number, offset: number): Page<string> => ({ items, total, limit: 10, offset });

describe("usePagedRecords", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("goes back to the first page when the current one comes back empty", async () => {
    const fetcher = vi.fn(async (_token: string, paging: { limit: number; offset: number }) =>
      paging.offset === 0 ? page(["a", "b"], 2, 0) : page([], 2, paging.offset),
    );
    const { result } = renderHook(() => usePagedRecords(fetcher), { wrapper });
    await waitFor(() => expect(result.current.state.status).toBe("success"));

    act(() => result.current.setOffset(10));

    await waitFor(() => expect(fetcher).toHaveBeenLastCalledWith("", { limit: 10, offset: 0 }, expect.anything()));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "success", data: { offset: 0 } }));
  });
});
