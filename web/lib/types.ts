// Mirrors meshycal/api/models.py — keep in sync.
//
// The api emits these shapes. If you change them on one side, change
// both. They are intentionally narrow renderer-facing projections, not
// Mesherra primitives.

export type MeetingStatus = "pending" | "accepted" | "declined";

export interface MeetingCard {
  id: string;
  status: MeetingStatus;
  counterparty_name: string;
  counterparty_principal_id: string;
  proposed_time: string | null;
  duration_minutes: number;
  title: string;
  last_updated: string;
}

export interface LedgerEntry {
  timestamp: string;
  actor: string;
  // Substrate-shaped Operation enum string (proposal/acceptance/…).
  // Second renderers may humanize from this and ignore `action`.
  operation: string;
  // Pre-composed human prose from the api. Convenient default.
  action: string;
  payload_hash_preview: string;
}

export interface MeetingDetail extends MeetingCard {
  agreement_hash: string | null;
  ledger: LedgerEntry[];
  reasoning: string;
}

export interface NewMeetingRequest {
  counterparty_principal_id: string;
  counterparty_name: string;
  duration_minutes: number;
  when_window: string;
  title: string;
}
