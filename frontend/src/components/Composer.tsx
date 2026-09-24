import { useState, type FormEvent, type KeyboardEvent } from "react";

interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
}

export function Composer({ disabled, onSend }: ComposerProps) {
  const [value, setValue] = useState("");

  const submit = () => {
    if (!value.trim() || disabled) return;
    onSend(value);
    setValue("");
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-3 border-t border-(--color-hairline) px-6 py-4">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={1}
        placeholder="Tulis sesuatu untuk dipikirkan bersama..."
        className="min-h-11 flex-1 resize-none bg-transparent text-(--color-paper)
          placeholder:text-(--color-muted) focus:outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="shrink-0 border border-(--color-signal) px-4 py-2 text-sm text-(--color-signal)
          transition-colors hover:bg-(--color-signal) hover:text-(--color-ink)
          disabled:cursor-not-allowed disabled:border-(--color-hairline) disabled:text-(--color-muted)
          disabled:hover:bg-transparent disabled:hover:text-(--color-muted)"
      >
        Kirim
      </button>
    </form>
  );
}
