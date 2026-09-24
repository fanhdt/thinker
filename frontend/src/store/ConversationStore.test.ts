import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock harus di-hoist sebelum import store, jadi pakai vi.mock (auto-hoisted oleh vitest).
vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    retryable: boolean;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
      this.retryable = status === 429;
    }
  },
  createConversation: vi.fn(),
  listMessages: vi.fn(),
  sendMessage: vi.fn(),
}));

import { createConversation, listMessages, sendMessage } from "../lib/api";
import { useConversationStore } from "./ConversationStore";

const initialState = useConversationStore.getState();

beforeEach(() => {
  localStorage.clear();
  useConversationStore.setState(initialState, true);
  vi.clearAllMocks();
});

describe("conversationStore.init", () => {
  it("creates a new conversation and saves its id when nothing is stored", async () => {
    vi.mocked(createConversation).mockResolvedValue({
      id: "conv-new",
      title: "Percakapan Baru",
      created_at: "2026-01-01",
    });

    await useConversationStore.getState().init();

    expect(createConversation).toHaveBeenCalledOnce();
    expect(useConversationStore.getState().conversationId).toBe("conv-new");
    expect(localStorage.getItem("thinker:conversation_id")).toBe("conv-new");
    expect(useConversationStore.getState().loading).toBe(false);
  });

  it("loads history for a conversation id already saved in localStorage", async () => {
    localStorage.setItem("thinker:conversation_id", "conv-existing");
    vi.mocked(listMessages).mockResolvedValue([{ id: "m1", role: "user", content: "halo", created_at: "2026-01-01" }]);

    await useConversationStore.getState().init();

    expect(listMessages).toHaveBeenCalledWith("conv-existing");
    expect(createConversation).not.toHaveBeenCalled();
    expect(useConversationStore.getState().messages).toHaveLength(1);
  });
});

describe("conversationStore.send", () => {
  beforeEach(() => {
    useConversationStore.setState({ conversationId: "conv-1" });
  });

  it("shows the message immediately (optimistic) then reconciles with the server reply", async () => {
    vi.mocked(sendMessage).mockResolvedValue({
      reply: "tentu, ada yang bisa dibantu",
      model: "gemini",
      conversation_id: "conv-1",
      used_planner: false,
      tasks: null,
    });

    const promise = useConversationStore.getState().send("halo Thinker");

    // Segera setelah dipanggil (sebelum await selesai), pesan user sudah
    // ada di state dengan status pending -- ini inti dari optimistic UI.
    const pendingState = useConversationStore.getState();
    expect(pendingState.messages).toHaveLength(1);
    expect(pendingState.messages[0].pending).toBe(true);
    expect(pendingState.sending).toBe(true);

    await promise;

    const finalState = useConversationStore.getState();
    expect(finalState.sending).toBe(false);
    expect(finalState.messages).toHaveLength(2);
    expect(finalState.messages[0].pending).toBe(false);
    expect(finalState.messages[1]).toMatchObject({
      role: "assistant",
      content: "tentu, ada yang bisa dibantu",
    });
  });

  it("marks the optimistic message as failed and sets an error when the server call fails", async () => {
    const { ApiError } = await import("../lib/api");
    vi.mocked(sendMessage).mockRejectedValue(new ApiError(500, "server meledak"));

    await useConversationStore.getState().send("halo");

    const state = useConversationStore.getState();
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].failed).toBe(true);
    expect(state.messages[0].pending).toBe(false);
    expect(state.error).toBe("server meledak");
  });

  it("does nothing for blank input", async () => {
    await useConversationStore.getState().send("   ");
    expect(sendMessage).not.toHaveBeenCalled();
    expect(useConversationStore.getState().messages).toHaveLength(0);
  });
});
