import Link from "next/link";
import { notFound } from "next/navigation";
import { Receipt } from "@/components/Receipt";
import { StatusBadge } from "@/components/StatusBadge";
import { getMeeting } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatTime(iso: string | null): string {
  if (!iso) return "Pending negotiation";
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default async function MeetingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const detail = await getMeeting(id);
  if (!detail) notFound();

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <Link
        href="/inbox"
        className="text-sm text-ink/60 underline-offset-4 hover:underline"
      >
        ← Back to inbox
      </Link>

      <header className="mt-4">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {detail.title}
          </h1>
          <StatusBadge status={detail.status} />
        </div>
        <p className="mt-1 text-sm text-ink/60">
          with {detail.counterparty_name}
        </p>
        <p className="mt-3 text-base">
          {formatTime(detail.proposed_time)}
          <span className="ml-2 text-ink/50">
            · {detail.duration_minutes} min
          </span>
        </p>
      </header>

      <div className="mt-8">
        <Receipt detail={detail} />
      </div>
    </main>
  );
}
