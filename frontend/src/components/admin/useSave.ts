import { useEffect, useRef, useState } from "react";
import { classifySaveError, type SaveFailure } from "../../api/adminCatalog";
import { useAuth } from "../../auth/authContext";

/** Runs one save at a time. A 401 ends the session; unmounting cancels the request. */
export function useSave(onSaved: () => void) {
  const { session, expireSession } = useAuth();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<SaveFailure | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function run(save: (token: string, signal: AbortSignal) => Promise<unknown>) {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine;
    setBusy(true);
    setFailure(null);
    try {
      await save(session?.token ?? "", mine.signal);
      onSaved();
    } catch (error) {
      const kind = classifySaveError(error);
      if (kind === "aborted") return;
      if (kind === "unauthenticated") expireSession();
      setFailure(kind);
    } finally {
      if (controller.current === mine) setBusy(false);
    }
  }

  return { busy, failure, run };
}
