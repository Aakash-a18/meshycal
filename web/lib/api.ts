// Thin fetch wrapper over meshycal.api.
//
// API base URL comes from NEXT_PUBLIC_MESHYCAL_API_URL (set in .env.local).
// Default is the local dev backend so the app works out of the box on a
// fresh clone.
//
// `as` selects which principal's view to render. All endpoints accept it
// as a query parameter; if omitted the api falls back to its configured
// default (alice in the sandbox).

import type {
  MeetingCard,
  MeetingDetail,
  NewMeetingRequest,
  Principal,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_MESHYCAL_API_URL ?? "http://localhost:8000";

function withAs(url: string, as?: string): string {
  if (!as) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}as=${encodeURIComponent(as)}`;
}

export async function listPrincipals(): Promise<Principal[]> {
  const r = await fetch(`${API_URL}/api/principals`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listPrincipals failed: ${r.status}`);
  return r.json();
}

export async function listMeetings(as?: string): Promise<MeetingCard[]> {
  const r = await fetch(withAs(`${API_URL}/api/meetings`, as), {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`listMeetings failed: ${r.status}`);
  return r.json();
}

export async function getMeeting(
  id: string,
  as?: string
): Promise<MeetingDetail | null> {
  const r = await fetch(
    withAs(`${API_URL}/api/meetings/${encodeURIComponent(id)}`, as),
    { cache: "no-store" }
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getMeeting failed: ${r.status}`);
  return r.json();
}

export async function submitMeeting(
  body: NewMeetingRequest,
  as?: string
): Promise<MeetingCard> {
  const r = await fetch(withAs(`${API_URL}/api/meetings`, as), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`submitMeeting failed: ${r.status}`);
  return r.json();
}
