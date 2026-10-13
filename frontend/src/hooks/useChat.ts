import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import {
  buildHistory,
  checkDraft,
  classifyChatError,
  sendChat,
  type ChatFailure,
  type ChatResponse,
  type DraftProblem,
} from "../api/chat";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  /** Structured answer of the assistant; the UI renders the quote from it, never from `content`. */
  response?: ChatResponse;
}

export interface ChatError {
  kind: Exclude<ChatFailure, "aborted"> | DraftProblem;
  /** Validated short sentence from the backend, if any. Render as text only. */
  serverMessage?: string;
}

const DEFAULT_COOLDOWN_SECONDS = 10;

/**
 * In-memory chat state (never persisted). One request at a time: a second send is ignored while
 * one is in flight, and answers that arrive after a reset or unmount are dropped.
 */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<ChatError | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const inFlight = useRef<AbortController | null>(null);
  const nextId = useRef(1);

  const abortCurrent = useCallback(() => {
    inFlight.current?.abort();
    inFlight.current = null;
  }, []);

  useEffect(() => abortCurrent, [abortCurrent]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1_000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const run = useCallback(
    async (thread: ChatMessage[]) => {
      const controller = new AbortController();
      inFlight.current = controller;
      setSending(true);
      setError(null);
      try {
        const answer = await sendChat(buildHistory(thread), controller.signal);
        if (inFlight.current !== controller) return;
        const reply: ChatMessage = { id: nextId.current++, role: "assistant", content: answer.reply, response: answer };
        setMessages([...thread, reply]);
      } catch (caught) {
        if (inFlight.current !== controller) return;
        const kind = classifyChatError(caught);
        if (kind === "aborted") return;
        const api = caught instanceof ApiError ? caught : undefined;
        if (kind === "rate_limited") setCooldown(api?.retryAfterSeconds ?? DEFAULT_COOLDOWN_SECONDS);
        setError({ kind, serverMessage: api?.serverMessage });
      }
      inFlight.current = null;
      setSending(false);
    },
    [],
  );

  /** Returns true when the text was accepted (the caller can clear its input). */
  const send = useCallback(
    (raw: string): boolean => {
      if (inFlight.current || cooldown > 0) return false;
      const problem = checkDraft(raw);
      if (problem) {
        setError({ kind: problem });
        return false;
      }
      const user: ChatMessage = { id: nextId.current++, role: "user", content: raw.trim() };
      const thread = [...messages, user];
      setMessages(thread);
      void run(thread);
      return true;
    },
    [messages, cooldown, run],
  );

  /** Sends the same thread again after a failure (its last message is still the user's). */
  const retry = useCallback(() => {
    if (inFlight.current || cooldown > 0 || messages.at(-1)?.role !== "user") return;
    void run(messages);
  }, [messages, cooldown, run]);

  const reset = useCallback(() => {
    abortCurrent();
    setMessages([]);
    setSending(false);
    setError(null);
    setCooldown(0);
  }, [abortCurrent]);

  return { messages, sending, error, cooldown, send, retry, reset };
}
