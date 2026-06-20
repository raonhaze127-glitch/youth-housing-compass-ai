import type { ApplicationStatus, HousingProgram } from "../types";

function getKoreanDate(date: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));

  return `${values.year}-${values.month}-${values.day}`;
}

export function getApplicationStatus(
  program: HousingProgram,
  now = new Date()
): ApplicationStatus {
  const today = getKoreanDate(now);

  if (!program.apply_start || !program.apply_end) return "unknown";

  if (today < program.apply_start) return "planned";
  if (today > program.apply_end) return "closed";
  return "open";
}
