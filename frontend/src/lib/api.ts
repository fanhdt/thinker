const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  retryable: boolean;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.retryable = status === 429;
  }
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface TaskResult {
  description: string;
  result: string;
  passed_evaluation: boolean;
  attempts: number;
}

export interface SendMessageResponse {
  reply: string;
  model: string;
  conversation_id: string;
  used_planner: boolean;
  tasks: TaskResult[] | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "Tidak bisa menghubungi server Thinker. Pastikan backend jalan.");
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // respons bukan JSON, pakai statusText apa adanya
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

export function createConversation(title = "Percakapan Baru"): Promise<Conversation> {
  return request<Conversation>("/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function listMessages(conversationId: string): Promise<Message[]> {
  return request<Message[]>(`/conversations/${conversationId}/messages`);
}

export function sendMessage(conversationId: string, message: string): Promise<SendMessageResponse> {
  return request<SendMessageResponse>(`/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}
