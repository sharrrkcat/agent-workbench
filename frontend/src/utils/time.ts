export function parseServerTime(value: string): Date {
  if (!value) return new Date(NaN);
  const hasTimezone = /Z$|[+-]\d{2}:\d{2}$/.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

export function formatMessageTime(value: string): string {
  const date = parseServerTime(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}
