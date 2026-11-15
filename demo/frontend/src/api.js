const BASE = import.meta.env.VITE_API_URL || "http://localhost:8001";

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const sendChat = (message, conversationId) =>
  request("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });

export const getBadge = (messageId) => request(`/messages/${messageId}/badge`);
export const getSamples = () => request("/samples");
export const getFreshGuardStatus = () => request("/freshguard/status");
