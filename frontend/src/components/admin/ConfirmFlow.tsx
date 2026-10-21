import { useRef, useState, type FormEvent } from "react";
import {
  applyAgentConfig,
  MAX_NOTE_CHARS,
  previewAgentConfig,
  type ConfigChange,
  type ConfigFailure,
  type Preview,
} from "../../api/adminAgentConfig";
import { es } from "../../copy/es";
import { Alert } from "../ui/Alert";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { Field, fieldProps, inputClass } from "./Field";
import { PreviewDetails } from "./PreviewDetails";
import { failureText, useConfigCall } from "./useConfigCall";

const t = es.agentAdmin;
const c = t.confirm;
export const CONFIRM_WORD = "APLICAR";

/** After these the outcome of an apply is unknown: the change may or may not have been saved. */
const UNKNOWN_OUTCOME: readonly ConfigFailure[] = ["transient", "unavailable", "confirmation_unavailable"];

export type NextStep = "review" | "confirm" | "conflict";

/** Where the admin lands after an apply fails: a spent or stale token needs a new preview. */
export function stepAfterFailure(kind: ConfigFailure): NextStep {
  if (kind === "token_stale") return "review";
  if (kind === "version_conflict") return "conflict";
  return "confirm";
}

/**
 * Double confirmation: modal 1 shows the changes and their risk, modal 2 asks for the word APLICAR
 * (and the password when the server wants it). The token and the password live in this component's
 * state only: nothing is stored or logged, and both vanish when the dialog closes.
 */
export function ConfirmFlow({
  change,
  initial,
  returnFocus,
  onClose,
  onApplied,
  onConflict,
  onUnknown,
}: {
  change: ConfigChange;
  initial: Preview;
  returnFocus: HTMLElement | null;
  onClose: () => void;
  onApplied: (version: number) => void;
  onConflict: () => void;
  /** Apply ended without a known outcome: the page reloads the stored configuration. */
  onUnknown: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(initial); // null: the token is spent, review again
  const [step, setStep] = useState<"review" | "confirm">("review");
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState("");
  const applying = useRef(false);
  const [maybeApplied, setMaybeApplied] = useState(false);
  const { busy, failure, run } = useConfigCall((e) => {
    if (applying.current && UNKNOWN_OUTCOME.includes(e.kind)) {
      // The token may be spent and the change saved: show the stored state and ask for a new preview.
      setMaybeApplied(true);
      setPreview(null);
      setStep("review");
      onUnknown();
      return;
    }
    const next = stepAfterFailure(e.kind);
    if (next === "conflict") onConflict();
    else if (next === "review") {
      setPreview(null);
      setStep("review");
    }
  });

  async function reviewAgain() {
    const fresh = await run((token, signal) => previewAgentConfig(change, token, signal));
    if (fresh) {
      setMaybeApplied(false);
      setPreview(fresh);
      setTyped("");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!preview || typed !== CONFIRM_WORD || busy) return;
    const confirmation = {
      confirmation_token: preview.confirmation_token,
      typed_confirmation: typed,
      ...(preview.requires_password ? { password } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
    };
    applying.current = true;
    const result = await run((token, signal) => applyAgentConfig(change, confirmation, token, signal));
    applying.current = false;
    setPassword("");
    if (result) onApplied(result.version);
  }

  const alert = failure ? <Alert tone="danger" title={maybeApplied ? c.maybeApplied : failureText(failure)} role="alert" /> : null;
  if (step === "review" || !preview) {
    return (
      <Modal title={c.reviewTitle} step="review" onClose={onClose} dismissible={!busy} returnFocus={returnFocus}>
        {alert}
        {preview ? (
          <>
            <PreviewDetails preview={preview} />
            <Alert tone="warn" title={c.impact} role="note" />
          </>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {c.cancel}
          </Button>
          {preview ? (
            <Button onClick={() => setStep("confirm")}>{c.continue}</Button>
          ) : (
            <Button onClick={() => void reviewAgain()} disabled={busy}>
              {c.reviewAgain}
            </Button>
          )}
        </div>
      </Modal>
    );
  }
  const ready = typed === CONFIRM_WORD && (!preview.requires_password || password.length > 0);
  return (
    <Modal title={c.confirmTitle} step="confirm" onClose={onClose} dismissible={!busy} returnFocus={returnFocus}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {alert}
        <Field id="confirm-typed" label={c.typeLabel(CONFIRM_WORD)}>
          {(p) => (
            <input {...fieldProps(p)} data-autofocus value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className={inputClass} />
          )}
        </Field>
        {preview.requires_password ? (
          <Field id="confirm-password" label={c.passwordLabel} hint={c.passwordHint}>
            {(p) => (
              <input {...fieldProps(p)} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" className={inputClass} />
            )}
          </Field>
        ) : null}
        <Field id="confirm-note" label={c.noteLabel} hint={c.noteHint(MAX_NOTE_CHARS)}>
          {(p) => <input {...fieldProps(p)} value={note} onChange={(e) => setNote(e.target.value)} maxLength={MAX_NOTE_CHARS} autoComplete="off" className={inputClass} />}
        </Field>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {c.cancel}
          </Button>
          <Button type="submit" disabled={!ready || busy}>
            {busy ? c.applying : c.apply}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
