import Link from "next/link";
import type { MeetingCard } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

function formatTime(iso: string | null): string {
  if (!iso) return "Pending negotiation";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function MeetingRow({ card }: { card: MeetingCard }) {
  return (
    <Link
      href={`/inbox/${card.id}`}
      className="block rounded-xl border border-ink/10 bg-white px-5 py-4 shadow-sm transition hover:border-ink/30 hover:shadow"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-base font-semibold">{card.title}</h3>
            <StatusBadge status={card.status} />
          </div>
          <p className="mt-1 text-sm text-ink/60">
            with <span className="text-ink/90">{card.counterparty_name}</span>
          </p>
        </div>
        <div className="shrink-0 text-right text-sm">
          <div className="font-medium">{formatTime(card.proposed_time)}</div>
          <div className="text-ink/50">{card.duration_minutes} min</div>
        </div>
      </div>
    </Link>
  );
}
