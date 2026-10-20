import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { countChars, MAX_MESSAGE_CHARS } from "../api/chat";
import { QuoteDetails } from "../components/chat/QuoteBreakdown";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button, ButtonLink } from "../components/ui/Button";
import { Container } from "../components/ui/Container";
import { PageHeader } from "../components/ui/PageHeader";
import { Spinner } from "../components/ui/Spinner";
import { es } from "../copy/es";
import { isMockMode } from "../env";
import { useBackend } from "../hooks/backendStatusContext";
import { useChat, type ChatError, type ChatMessage } from "../hooks/useChat";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const t = es.chat;

export default function ChatPage() {
  useDocumentTitle(es.titles.chat);
  const { status: backend } = useBackend();
  const [draft, setDraft] = useState("");
  const { messages, sending, error, cooldown, send, retry, reset } = useChat({
    onRestore: (text) => setDraft((current) => current || text),
  });
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const inputId = useId();
  const helpId = useId();
  const listHeadingId = useId();

  // Keep the newest message in view (no animated scrolling, so reduced motion is respected).
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, sending]);

  const submit = () => {
    if (send(draft)) setDraft("");
    inputRef.current?.focus();
  };
  // A clicked option goes through the normal send path, as if the customer had typed it.
  const pick = (option: string) => {
    send(option);
    inputRef.current?.focus();
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const used = countChars(draft);
  const blocked = sending || cooldown > 0;

  return (
    <>
      <PageHeader title={t.title} lead={t.lead} />
      <Container className="max-w-3xl py-8">
        {isMockMode() ? <p className="mb-4 text-sm text-ink-muted">{t.demoHint}</p> : null}
        <h2 id={listHeadingId} className="sr-only">
          {t.conversationTitle}
        </h2>
        <div
          ref={logRef}
          role="log"
          aria-live="polite"
          aria-labelledby={listHeadingId}
          className="max-h-[60vh] min-h-40 overflow-y-auto rounded-card border border-line bg-surface-alt p-4"
        >
          {messages.length === 0 ? <p className="text-ink-muted">{t.empty}</p> : null}
          <ul className="space-y-4">
            {messages.map((message, index) => (
              <MessageItem
                key={message.id}
                message={message}
                onPick={index === messages.length - 1 && !sending ? pick : undefined}
                pickDisabled={cooldown > 0}
              />
            ))}
            {sending ? (
              <li className="flex items-center gap-2 text-ink-muted">
                <Spinner />
                <span>{t.typing}</span>
              </li>
            ) : null}
          </ul>
        </div>

        {error ? (
          <div className="mt-4 space-y-3">
            <ErrorNotice error={error} cooldown={cooldown} waking={backend !== "ok"} />
            {error.kind === "transient" || error.kind === "unexpected" ? (
              <Button
                variant="secondary"
                disabled={blocked}
                onClick={() => {
                  retry();
                  inputRef.current?.focus();
                }}
              >
                {es.common.retry}
              </Button>
            ) : null}
            {error.kind === "disabled" ? <ButtonLink to="/servicios" variant="secondary">{t.catalogLink}</ButtonLink> : null}
          </div>
        ) : null}

        <form onSubmit={onSubmit} className="mt-4 space-y-2">
          <label htmlFor={inputId} className="block text-sm font-semibold">
            {t.inputLabel}
          </label>
          <textarea
            id={inputId}
            ref={inputRef}
            rows={3}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            aria-describedby={helpId}
            aria-invalid={used > MAX_MESSAGE_CHARS}
            className="block w-full rounded-control border border-line bg-surface px-3 py-2 text-base"
          />
          <p id={helpId} className="text-xs text-ink-muted">
            {t.inputHelp} {t.counter(used, MAX_MESSAGE_CHARS)}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={blocked}>
              {t.send}
            </Button>
            <Button
              variant="secondary"
              disabled={messages.length === 0 && !sending}
              onClick={() => {
                reset();
                setDraft("");
                inputRef.current?.focus();
              }}
            >
              {t.newConversation}
            </Button>
          </div>
        </form>
      </Container>
    </>
  );
}

function MessageItem({
  message,
  onPick,
  pickDisabled,
}: {
  message: ChatMessage;
  /** Set only on the latest message while no request is in flight; options stay hidden otherwise. */
  onPick?: (option: string) => void;
  pickDisabled?: boolean;
}) {
  const mine = message.role === "user";
  const options = onPick ? (message.response?.options ?? []) : [];
  return (
    <li className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[90%] rounded-card px-4 py-3 ${mine ? "bg-brand-600 text-white" : "border border-line bg-surface"}`}>
        <p className="text-xs font-semibold opacity-80">{mine ? t.authorUser : t.authorAssistant}</p>
        {/* Plain text only: React escapes it and pre-wrap keeps line breaks. Never HTML or links. */}
        <p className="break-words whitespace-pre-wrap">{message.content}</p>
        {message.response ? (
          <>
            <QuoteDetails response={message.response} />
            <p className="mt-2">
              <Badge>{t.source[message.response.reply_source]}</Badge>
            </p>
          </>
        ) : null}
        {options.length > 0 && onPick ? (
          // Option texts come from the catalog but are still rendered as plain text.
          <div role="group" aria-label={t.optionsLabel} className="mt-3 flex flex-wrap gap-2">
            {options.map((option) => (
              <Button key={option} variant="secondary" disabled={pickDisabled} onClick={() => onPick(option)}>
                {option}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function ErrorNotice({ error, cooldown, waking }: { error: ChatError; cooldown: number; waking: boolean }) {
  const copy = t.errors[error.kind];
  // The backend sentence is plain text; it is only used for classes where it adds information.
  const useServer = error.kind === "rate_limited" || error.kind === "budget" || error.kind === "invalid";
  const body = useServer && error.serverMessage ? error.serverMessage : copy.body;
  const tone = error.kind === "disabled" || error.kind === "budget" ? "info" : "danger";
  return (
    <Alert tone={tone} title={copy.title} role="alert">
      {body}
      {error.kind === "rate_limited" && cooldown > 0 ? <span className="block">{t.cooldown(cooldown)}</span> : null}
      {error.kind === "transient" && waking ? <span className="block">{t.waking}</span> : null}
    </Alert>
  );
}
