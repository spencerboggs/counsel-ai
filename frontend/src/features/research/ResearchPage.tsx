import { ProgressStages } from "@/components";

export function ResearchPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">
          Research
        </h1>
        <p className="mt-2 text-sm text-ink-muted">
          Research run history and live stage progress will appear here.
        </p>
      </header>

      <div className="border border-border bg-surface-raised/80 p-5">
        <ProgressStages
          stages={[
            { id: "1", label: "Universe loaded", status: "pending" },
            { id: "2", label: "Initial screening", status: "pending" },
            { id: "3", label: "Candidate research", status: "pending" },
            { id: "4", label: "Fundamental analysis", status: "pending" },
            { id: "5", label: "Technical analysis", status: "pending" },
            { id: "6", label: "Evidence adjudication", status: "pending" },
            { id: "7", label: "Counsel debate", status: "pending" },
            { id: "8", label: "Final scoring", status: "pending" },
          ]}
        />
      </div>
    </div>
  );
}
