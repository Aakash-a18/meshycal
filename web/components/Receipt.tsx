import type { MeetingDetail } from "@/lib/types";

function formatStamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function Receipt({ detail }: { detail: MeetingDetail }) {
  return (
    <section className="rounded-2xl bg-receipt px-6 py-6 ring-1 ring-ink/10">
      <header className="flex items-center justify-between border-b border-ink/10 pb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ink/60">
          Receipt
        </h2>
        {detail.agreement_hash && (
          <code className="font-mono text-xs text-ink/60">
            {detail.agreement_hash.slice(0, 16)}…
          </code>
        )}
      </header>

      <p className="mt-4 text-sm leading-relaxed text-ink/80">
        {detail.reasoning}
      </p>

      <ol className="mt-5 space-y-2 border-t border-ink/10 pt-4">
        {detail.ledger.map((entry, idx) => (
          <li
            key={`${entry.timestamp}-${idx}`}
            className="grid grid-cols-[auto_1fr_auto] items-baseline gap-3 text-sm"
          >
            <span className="font-mono text-xs text-ink/50">
              {formatStamp(entry.timestamp)}
            </span>
            <span>
              <span className="font-medium">{entry.actor}</span>{" "}
              <span className="text-ink/70">{entry.action}</span>
            </span>
            <code className="font-mono text-xs text-ink/40">
              {entry.payload_hash_preview}
            </code>
          </li>
        ))}
      </ol>
    </section>
  );
}
