import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends the trimmed text on Enter and clears the input", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Composer disabled={false} onSend={onSend} />);

    const textarea = screen.getByPlaceholderText(/tulis sesuatu/i);
    await user.type(textarea, "  halo dunia  {Enter}");

    expect(onSend).toHaveBeenCalledWith("  halo dunia  ");
    expect(textarea).toHaveValue("");
  });

  it("does not send on Shift+Enter, adds a newline instead", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Composer disabled={false} onSend={onSend} />);

    const textarea = screen.getByPlaceholderText(/tulis sesuatu/i);
    await user.type(textarea, "baris satu{Shift>}{Enter}{/Shift}baris dua");

    expect(onSend).not.toHaveBeenCalled();
    expect(textarea).toHaveValue("baris satu\nbaris dua");
  });

  it("disables the send button while disabled=true, even with text typed", async () => {
    const user = userEvent.setup();
    render(<Composer disabled={true} onSend={vi.fn()} />);

    const textarea = screen.getByPlaceholderText(/tulis sesuatu/i);
    await user.type(textarea, "halo");

    expect(screen.getByRole("button", { name: /kirim/i })).toBeDisabled();
  });

  it("disables the send button when the input is empty", () => {
    render(<Composer disabled={false} onSend={vi.fn()} />);
    expect(screen.getByRole("button", { name: /kirim/i })).toBeDisabled();
  });
});
