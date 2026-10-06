import { Link } from "react-router-dom";
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { active, useJob } from "../api/queries";
import { useJobProgress } from "../hooks/useJobProgress";
import { ErrorNotice, Loading } from "./Feedback";

export function JobProgress({ id }: { id: string }) {
  const query = useJob(id);
  const frame = useJobProgress(id);
  const client = useQueryClient();
  const progress = frame || query.data;
  const status = progress?.status;
  useEffect(() => {
    if (status && !active(status))
      void client.invalidateQueries({
        predicate: (query) =>
          !["job", "jobs"].includes(String(query.queryKey[0])),
      });
  }, [status, client]);
  if (query.isPending) return <Loading text="Checking collection status…" />;
  if (query.error) return <ErrorNotice error={query.error} />;
  if (!progress) return null;
  return (
    <div className="job-progress" aria-live="polite">
      <div className="section-line">
        <strong>Job {progress.status}</strong>
        <Link to="/jobs">View jobs</Link>
      </div>
      <progress value={progress.progress} max={100} />
      <p>
        {progress.progress}% ·{" "}
        {progress.error_message ||
          (active(progress.status)
            ? "The worker is executing this job."
            : "Job finished. Inspect its saved results and status.")}
      </p>
      {typeof query.data.result.analysis_id === "string" && (
        <Link
          className="button secondary"
          to={`/analyses/${query.data.result.analysis_id}`}
        >
          View saved analysis
        </Link>
      )}
    </div>
  );
}
