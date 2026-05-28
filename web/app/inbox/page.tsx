import Link from "next/link";
import { MeetingRow } from "@/components/MeetingRow";
import { listMeetings } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function InboxPage() {
  const cards = await listMeetings();
  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
          <p className="mt-1 text-sm text-ink/60">
            What your butler did while you were away.
          </p>
        </div>
        <Link
          href="/inbox/new"
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-cream hover:bg-ink/90"
        >
          New meeting
        </Link>
      </header>

      <ul className="mt-6 space-y-3">
        {cards.map((c) => (
          <li key={c.id}>
            <MeetingRow card={c} />
          </li>
        ))}
      </ul>
    </main>
  );
}
