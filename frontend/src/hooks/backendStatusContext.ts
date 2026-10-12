import { createContext, useContext } from "react";
import type { BackendStatus } from "./useBackendStatus";

export interface BackendStatusValue {
  status: BackendStatus;
  retry: () => void;
}

export const BackendStatusContext = createContext<BackendStatusValue>({
  status: "ok",
  retry: () => {},
});

/** Backend status shared by the warm-up banner and the pages that load data. */
export function useBackend(): BackendStatusValue {
  return useContext(BackendStatusContext);
}
