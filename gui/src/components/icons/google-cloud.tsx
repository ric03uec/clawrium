interface IconProps {
  className?: string;
  title?: string;
}

export function GoogleCloudIcon({ className = "h-4 w-4", title }: IconProps) {
  return (
    <svg
      role="img"
      aria-label={title ?? "Google Cloud"}
      viewBox="0 0 24 24"
      className={className}
      fill="currentColor"
    >
      <path d="M12.19 2.38a9.344 9.344 0 0 0-9.234 6.893c.053-.02-.055.013 0 0-3.875 2.551-3.922 8.11-.247 10.941l.006-.007-.007.003a6.524 6.524 0 0 0 3.56 1.052h10.472a6.305 6.305 0 0 0 4.36-1.74 5.885 5.885 0 0 0 .597-7.852l.011.009-.004-.005a9.344 9.344 0 0 0-9.514-9.294M12 4.595a7.09 7.09 0 0 1 7.071 6.588l.143 1.19 1.07.527a3.63 3.63 0 0 1-.325 6.58l-.357.106H6.268a4.27 4.27 0 0 1-2.321-.68l-.187-.133-.17-.14a4.206 4.206 0 0 1 .262-6.661l.96-.66.156-1.142A7.09 7.09 0 0 1 12 4.596z" />
    </svg>
  );
}
