interface IconProps {
  className?: string;
  title?: string;
}

export function AmdIcon({ className = "h-3.5 w-3.5", title }: IconProps) {
  return (
    <svg
      role="img"
      aria-label={title ?? "AMD"}
      viewBox="0 0 24 24"
      className={className}
      fill="currentColor"
    >
      <path d="M18.124 6 23 10.876v7.122H15.876L11 13.123h7.124V6zM5.876 18l-2.06 2.062H1l4.876-4.876V6h7.124L8.124 10.876H5.876V18z" />
    </svg>
  );
}
