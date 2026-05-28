"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Principal } from "@/lib/types";

export function PrincipalSwitcher({
  principals,
  current,
}: {
  principals: Principal[];
  current: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("as", e.target.value);
    router.push(`${pathname}?${params.toString()}`);
    router.refresh();
  }

  return (
    <label className="inline-flex items-center gap-2 text-sm text-ink/70">
      Viewing as
      <select
        value={current}
        onChange={onChange}
        className="rounded-md border border-ink/15 bg-white px-2 py-1 text-sm shadow-sm focus:border-ink/40 focus:outline-none"
      >
        {principals.map((p) => (
          <option key={p.alias} value={p.alias}>
            {p.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}
