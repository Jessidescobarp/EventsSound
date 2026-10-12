/** Neutral stand-in for photography that does not exist yet. */
export function ImagePlaceholder({ label, className = "" }: { label: string; className?: string }) {
  return (
    <div
      role="img"
      aria-label={label}
      className={`aspect-video w-full rounded-card bg-linear-to-br from-brand-900 via-brand-700 to-brand-500 ${className}`}
    />
  );
}
