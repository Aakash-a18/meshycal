import Link from "next/link";
import { InboxAutoRefresh } from "@/components/InboxAutoRefresh";
import { MeetingRow } from "@/components/MeetingRow";
import { PrincipalSwitcher } from "@/components/PrincipalSwitcher";
import { listMeetings, listPrincipals } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<{ as?: string }>;
}) {
  const { as } = await searchParams;
  const [cards, principals] = await Promise.all([
    listMeetings(as),
    listPrincipals(),
  ]);
  const current =
    as && principals.some((p) => p.alias === as) ? as : principals[0]?.alias;
  const newMeetingHref = `/inbox/new${as ? `?as=${as}` : ""}`;

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <InboxAutoRefresh />
      <div className="flex items-start justify-between gap-4">
        <PrincipalSwitcher principals={principals} current={current ?? ""} />
        <Link
          href={newMeetingHref}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-cream hover:bg-ink/90"
        >
          New meeting
        </Link>
      </div>

      <header className="mt-6">
        <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
        <p className="mt-1 text-sm text-ink/60">
          What your butler did while you were away.
        </p>
      </header>

      {cards.length === 0 ? (
        <p className="mt-8 rounded-lg border border-dashed border-ink/15 bg-white px-5 py-8 text-center text-sm text-ink/60">
          No meetings yet. Click <span className="font-medium">New meeting</span> to
          start a negotiation.
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {cards.map((c) => (
            <li key={c.id}>
              <MeetingRow card={c} viewingAs={as} />
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
