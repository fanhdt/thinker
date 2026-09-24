import type { DisplayMessage } from "../store/ConversationStore"
import { TaskTrace } from "./TaskTrace";

const timeFormatter = new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit" });

export function MessageItem({ message }: { message: DisplayMessage }) {
  const isUser = message.role === "user";
  const label = isUser ? "Kamu" : "Thinker";
  const time = timeFormatter.format(new Date(message.created_at));

  return (
    <article className="animate-[fadein_180ms_ease-out] border-b border-(--color-hairline) py-5">
      <header className="flex items-baseline justify-between font-serif text-sm">
        <span className={isUser ? "text-(--color-paper)" : "text-(--color-signal)"}>
          {label}
          {message.usedPlanner && <span className="ml-2 font-sans text-xs text-(--color-amber)">merencanakan</span>}
        </span>
        <span className="text-(--color-muted)">{message.pending ? "mengirim..." : message.failed ? "gagal terkirim" : time}</span>
      </header>
      <p className="mt-2 whitespace-pre-wrap leading-relaxed text-(--color-paper)">{message.content}</p>
      {message.tasks && message.tasks.length > 0 && <TaskTrace tasks={message.tasks} />}
    </article>
  );
}
