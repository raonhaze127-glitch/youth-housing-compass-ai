import type { ApplicationStatus } from "@/lib/types";

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  open: "접수중",
  planned: "모집예정",
  closed: "마감"
};

export function ApplicationStatusBadge({ status }: { status: ApplicationStatus }) {
  return (
    <span className={`application-status ${status}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}
