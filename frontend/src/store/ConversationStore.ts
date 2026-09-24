import { create } from "zustand";
import { ApiError, createConversation, listMessages, sendMessage, type Message, type TaskResult } from "../lib/api";

const STORAGE_KEY = "thinker:conversation_id";

// Pesan optimis yang belum dikonfirmasi server dapat field tambahan supaya
// UI bisa menampilkan status pending/gagal tanpa menunggu round-trip.
export interface DisplayMessage extends Message {
  pending?: boolean;
  failed?: boolean;
  usedPlanner?: boolean;
  tasks?: TaskResult[] | null;
}

interface ConversationStore {
  conversationId: string | null;
  messages: DisplayMessage[];
  loading: boolean;
  sending: boolean;
  error: string | null;
  init: () => Promise<void>;
  send: (text: string) => Promise<void>;
}

/**
 * Global store untuk percakapan aktif. Kenapa Zustand dan bukan cuma
 * useState di komponen (lihat DECISIONS.md ADR-014 untuk detail trade-off):
 * begitu Memory/Goals/Tasks view (Fase 8, §20 master prompt) ditambahkan,
 * mereka perlu tahu percakapan mana yang aktif tanpa prop-drilling manual
 * lewat App.tsx. Store ini sengaja hanya menyimpan SATU percakapan aktif --
 * daftar banyak percakapan adalah scope increment berikutnya, bukan sekarang.
 */
export const useConversationStore = create<ConversationStore>((set, get) => ({
  conversationId: null,
  messages: [],
  loading: true,
  sending: false,
  error: null,

  init: async () => {
    try {
      const savedId = localStorage.getItem(STORAGE_KEY);
      if (savedId) {
        const history = await listMessages(savedId);
        set({ conversationId: savedId, messages: history });
      } else {
        const conversation = await createConversation();
        localStorage.setItem(STORAGE_KEY, conversation.id);
        set({ conversationId: conversation.id });
      }
    } catch {
      // Percakapan tersimpan mungkin sudah tidak ada (mis. DB direset) --
      // mulai percakapan baru daripada macet di error permanen.
      try {
        const conversation = await createConversation();
        localStorage.setItem(STORAGE_KEY, conversation.id);
        set({ conversationId: conversation.id });
      } catch (fallbackErr) {
        set({ error: describeError(fallbackErr) });
      }
    } finally {
      set({ loading: false });
    }
  },

  send: async (text: string) => {
    const trimmed = text.trim();
    const { conversationId, sending } = get();
    if (!trimmed || !conversationId || sending) return;

    const tempId = `pending-${Date.now()}`;
    set((state) => ({
      error: null,
      sending: true,
      messages: [
        ...state.messages,
        {
          id: tempId,
          role: "user",
          content: trimmed,
          created_at: new Date().toISOString(),
          pending: true,
        },
      ],
    }));

    try {
      const result = await sendMessage(conversationId, trimmed);
      set((state) => ({
        sending: false,
        messages: [
          ...state.messages.map((m) => (m.id === tempId ? { ...m, pending: false } : m)),
          {
            id: `${tempId}-reply`,
            role: "assistant" as const,
            content: result.reply,
            created_at: new Date().toISOString(),
            usedPlanner: result.used_planner,
            tasks: result.tasks,
          },
        ],
      }));
    } catch (err) {
      set((state) => ({
        sending: false,
        error: describeError(err),
        messages: state.messages.map((m) => (m.id === tempId ? { ...m, pending: false, failed: true } : m)),
      }));
    }
  },
}));

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.retryable) return "Thinker sedang dibatasi (rate limit). Coba lagi sebentar lagi.";
    return err.message || "Ada yang salah di sisi server.";
  }
  return "Ada yang salah dan tidak terduga.";
}
