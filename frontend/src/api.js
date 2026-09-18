const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function getSession(sessionId) {
  const url = sessionId
    ? `${API_URL}/api/session?session_id=${encodeURIComponent(sessionId)}`
    : `${API_URL}/api/session`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`getSession failed: ${res.status}`);
  return res.json();
}

export async function sendMessage(sessionId, message) {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) throw new Error(`sendMessage failed: ${res.status}`);
  return res.json();
}

export async function resetSession(sessionId) {
  const res = await fetch(`${API_URL}/api/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`resetSession failed: ${res.status}`);
  return res.json();
}
