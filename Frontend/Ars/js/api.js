/**
 * Thin client for the local Ars Ollama bridge (ars_server.py).
 * Same-origin by default when the UI is served by that server.
 * On static hosts (Azure/npm serve), /api/* may return SPA HTML — fall back to loops.json.
 */
const Api = {
  base: window.ARS_API_BASE || "",

  async health() {
    const response = await fetch(`${this.base}/api/health`);
    return response.json();
  },

  async _readJsonResponse(response) {
    const type = (response.headers.get("content-type") || "").toLowerCase();
    if (!type.includes("application/json") && !type.includes("+json")) {
      return null;
    }
    try {
      return await response.json();
    } catch (_) {
      return null;
    }
  },

  async loadLoops() {
    try {
      const response = await fetch(`${this.base}/api/loops`);
      if (response.ok) {
        const data = await this._readJsonResponse(response);
        if (data && Array.isArray(data.loops)) return data;
      }
    } catch (_) {
      /* fall through to static JSON */
    }

    const response = await fetch("./assets/docs/loops.json");
    if (!response.ok) throw new Error("Could not load experience loops");
    const data = await this._readJsonResponse(response);
    if (!data || !Array.isArray(data.loops)) {
      throw new Error("loops.json is missing or invalid");
    }
    return data;
  },

  async createSession() {
    const response = await fetch(`${this.base}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!response.ok) throw new Error("Could not create chat session");
    return response.json();
  },

  async resetSession(sessionId) {
    await fetch(`${this.base}/api/session/reset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId || null }),
    });
  },

  async chat(sessionId, message) {
    const response = await fetch(`${this.base}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message,
      }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const err = new Error(data.error || "Chat request failed");
      err.reply = data.reply;
      throw err;
    }
    return data;
  },
};
