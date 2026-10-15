import { useCallback, useEffect, useState } from "react";
import { classifyRecordsError, PAGE_SIZE, type Page, type Paging, type RecordsFailure } from "../api/records";
import { useAuth } from "../auth/authContext";
import { useRequest } from "./useRequest";

type Fetcher<T> = (token: string, paging: Paging, signal?: AbortSignal) => Promise<Page<T>>;

/**
 * One paginated, authenticated list. `fetcher` must be a module-level function. A 401 means the
 * server no longer accepts the token: the session ends and the guard sends the user to login.
 */
export function usePagedRecords<T>(fetcher: Fetcher<T>) {
  const { session, expireSession } = useAuth();
  const token = session?.token ?? "";
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => fetcher(token, { limit: PAGE_SIZE, offset }, signal),
    [fetcher, token, offset],
  );
  const { state, reload } = useRequest(load);
  const failure: RecordsFailure | null =
    state.status === "error" ? classifyRecordsError(state.error) : null;

  useEffect(() => {
    if (failure === "unauthenticated") expireSession();
  }, [failure, expireSession]);

  // The list shrank under the reader: an empty page past the start sends them back to the start.
  // Adjusting state during render (guarded by the condition) is the React-sanctioned way.
  if (state.status === "success" && state.data.items.length === 0 && offset > 0) setOffset(0);

  return { state, failure, setOffset, reload };
}
