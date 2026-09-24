import { useEffect, useRef } from "react";
import { useConversationStore } from "./store/ConversationStore";
import { MessageItem } from "./components/MessageItem";
import { Composer } from "./components/Composer";

export default function App() {
  const { messages, loading, sending, error, init, send } = useConversationStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    init();
  }, [init]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="mx-auto flex h-screen max-w-2xl flex-col px-6">
      <header className="border-b border-color: var(--color-hairline) py-6">
        <h1 className="font-serif text-2xl text-paper">Thinker</h1>
        <p className="mt-1 text-sm text-muted">Coba coba aja hehee</p>
      </header>

      <main className="flex-1 overflow-y-auto">
        {loading ? (
          <p className="py-10 text-center text-sm text-muted">memuat percakapan...</p>
        ) : messages.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted">belum ada apa-apa di sini -- mulai dengan menulis sesuatu di bawah</p>
        ) : (
          messages.map((message) => <MessageItem key={message.id} message={message} />)
        )}
        <div ref={bottomRef} />
      </main>

      {error && <p className="border-t border-danger bg-color-panel px-6 py-2 text-sm text-danger">{error}</p>}

      <div className="-mx-6">
        <Composer disabled={loading || sending} onSend={send} />
      </div>
    </div>
  );
}
