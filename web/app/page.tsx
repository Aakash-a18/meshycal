import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">MeshyCal</h1>
      <p className="mt-3 text-sm text-ink/70">
        Your scheduling butler. Agents negotiate meetings on your behalf;
        you see the receipt.
      </p>
      <Link
        href="/inbox"
        className="mt-8 inline-block rounded-lg bg-ink px-4 py-2 text-sm font-medium text-cream hover:bg-ink/90"
      >
        Open inbox
      </Link>
    </main>
  );
}
