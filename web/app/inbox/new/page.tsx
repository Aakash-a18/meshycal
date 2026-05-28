"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { submitMeeting } from "@/lib/api";

const DURATIONS = [15, 30, 45, 60] as const;

export default function NewMeetingPage() {
  const router = useRouter();
  const [counterpartyName, setCounterpartyName] = useState("");
  const [counterpartyPid, setCounterpartyPid] = useState("");
  const [duration, setDuration] = useState<number>(30);
  const [whenWindow, setWhenWindow] = useState("");
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await submitMeeting({
        counterparty_principal_id: counterpartyPid,
        counterparty_name: counterpartyName,
        duration_minutes: duration,
        when_window: whenWindow,
        title,
      });
      router.push("/inbox");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "submit failed");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <Link
        href="/inbox"
        className="text-sm text-ink/60 underline-offset-4 hover:underline"
      >
        ← Back to inbox
      </Link>

      <h1 className="mt-4 text-2xl font-semibold tracking-tight">
        New meeting
      </h1>
      <p className="mt-1 text-sm text-ink/60">
        Tell your butler what you want. It will negotiate the slot with
        the other side&apos;s agent.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field label="Who (name)">
          <input
            required
            type="text"
            value={counterpartyName}
            onChange={(e) => setCounterpartyName(e.target.value)}
            placeholder="Bob Lin"
            className={inputClass}
          />
        </Field>

        <Field label="Their address">
          <input
            required
            type="text"
            value={counterpartyPid}
            onChange={(e) => setCounterpartyPid(e.target.value)}
            placeholder="bob@sandbox.local"
            className={inputClass}
          />
        </Field>

        <Field label="How long">
          <select
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className={inputClass}
          >
            {DURATIONS.map((d) => (
              <option key={d} value={d}>
                {d} min
              </option>
            ))}
          </select>
        </Field>

        <Field label="When (rough window)">
          <input
            required
            type="text"
            value={whenWindow}
            onChange={(e) => setWhenWindow(e.target.value)}
            placeholder="next week, weekday afternoon"
            className={inputClass}
          />
        </Field>

        <Field label="What's it about">
          <input
            required
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Coffee chat"
            className={inputClass}
          />
        </Field>

        {error && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-cream hover:bg-ink/90 disabled:opacity-50"
        >
          {submitting ? "Sending…" : "Ask my butler"}
        </button>
      </form>
    </main>
  );
}

const inputClass =
  "block w-full rounded-md border border-ink/15 bg-white px-3 py-2 text-sm shadow-sm focus:border-ink/40 focus:outline-none";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-ink/80">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
