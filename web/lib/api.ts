// Thin fetch wrapper over meshycal.api.
//
// API base URL comes from NEXT_PUBLIC_MESHYCAL_API_URL (set in .env.local).
// Default is the local dev backend so the app works out of the box on a
// fresh clone.

import type { MeetingCard, MeetingDetail, NewMeetingRequest } from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_MESHYCAL_API_URL ?? "http://localhost:8000";

export async function listMeetings(): Promise<MeetingCard[]> {
  const r = await fetch(`${API_URL}/api/meetings`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listMeetings failed: ${r.status}`);
  return r.json();
}

export async function getMeeting(id: string): Promise<MeetingDetail | null> {
  const r = await fetch(`${API_URL}/api/meetings/${encodeURIComponent(id)}`, {
    cache: "no-store",
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getMeeting failed: ${r.status}`);
  return r.json();
}

export async function submitMeeting(
  body: NewMeetingRequest
): Promise<MeetingCard> {
  const r = await fetch(`${API_URL}/api/meetings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`submitMeeting failed: ${r.status}`);
  return r.json();
}
