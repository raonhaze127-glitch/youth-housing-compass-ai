const USER_KEY = "youth-housing-compass:user-id";

export function getBrowserUserId() {
  const existing = localStorage.getItem(USER_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  localStorage.setItem(USER_KEY, created);
  return created;
}
