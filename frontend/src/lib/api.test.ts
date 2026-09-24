import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createConversation, sendMessage } from "./api";

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the right method/body and returns parsed JSON on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "conv-1", title: "Percakapan Baru", created_at: "2026-01-01" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createConversation();

    expect(result.id).toBe("conv-1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/conversations");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ title: "Percakapan Baru" });
  });

  it("throws an ApiError carrying the backend's error detail on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: async () => ({ detail: "Percakapan tidak ditemukan" }),
      }),
    );

    await expect(sendMessage("missing-id", "halo")).rejects.toMatchObject({
      status: 404,
      message: "Percakapan tidak ditemukan",
      retryable: false,
    });
  });

  it("marks 429 responses as retryable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 429,
        statusText: "Too Many Requests",
        json: async () => ({}),
      }),
    );

    try {
      await sendMessage("conv-1", "halo");
      expect.unreachable("harusnya melempar ApiError");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).retryable).toBe(true);
    }
  });

  it("wraps a network failure (fetch rejects) into a friendly ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));

    await expect(createConversation()).rejects.toMatchObject({
      status: 0,
      retryable: false,
    });
  });
});
