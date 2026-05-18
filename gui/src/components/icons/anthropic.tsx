interface IconProps {
  className?: string;
  title?: string;
}

export function AnthropicIcon({ className = "h-4 w-4", title }: IconProps) {
  return (
    <svg
      role="img"
      aria-label={title ?? "Anthropic"}
      viewBox="0 0 24 24"
      className={className}
      fill="currentColor"
    >
      <path d="M17.304 3.541h-3.483l6.15 16.918h3.483l-6.15-16.918zm-10.608 0L.546 20.459H4.1l1.27-3.564h6.476l1.27 3.564h3.554L10.52 3.541H6.696zm.912 10.401L9.9 7.864l2.292 6.078H7.608z" />
    </svg>
  );
}
