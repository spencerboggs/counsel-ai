import { EvidenceCard } from "@/components";

export function EvidencePage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
          Evidence
        </h1>
        <p className="mt-2 text-sm text-ink-muted">
          Every substantive claim becomes an evidence item with provenance. The
          ledger fills when research runs execute.
        </p>
      </header>

      <EvidenceCard emptyMessage="Evidence store is empty. No fabricated claims are shown." />
    </div>
  );
}
