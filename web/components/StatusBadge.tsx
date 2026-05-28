import type { MeetingStatus } from "@/lib/types";

const TONES: Record<MeetingStatus, string> = {
  pending: "bg-amber-100 text-amber-900 ring-amber-200",
  accepted: "bg-emerald-100 text-emerald-900 ring-emerald-200",
  declined: "bg-stone-200 text-stone-700 ring-stone-300",
};

const LABELS: Record<MeetingStatus, string> = {
  pending: "Needs your call",
  accepted: "Booked",
  declined: "Declined",
};

export function StatusBadge({ status }: { status: MeetingStatus }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
