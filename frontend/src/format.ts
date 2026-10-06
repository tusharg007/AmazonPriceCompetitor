export function amount(
  price?: string | null,
  currency?: string | null,
): string {
  if (price == null || !Number.isFinite(Number(price))) return "Unavailable";
  if (!currency) return `${price} (currency unknown)`;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 4,
    }).format(Number(price));
  } catch {
    return `${price} ${currency || ""}`.trim();
  }
}

export function timestamp(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not collected";
}
