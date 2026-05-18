interface IconProps {
  className?: string;
  title?: string;
}

export function OpenRouterIcon({ className = "h-4 w-4", title }: IconProps) {
  return (
    <svg
      role="img"
      aria-label={title ?? "OpenRouter"}
      viewBox="0 0 24 24"
      className={className}
      fill="currentColor"
    >
      <path d="M12 1.5C6.202 1.5 1.5 6.202 1.5 12S6.202 22.5 12 22.5 22.5 17.798 22.5 12 17.798 1.5 12 1.5zm0 2.25a8.25 8.25 0 0 1 8.25 8.25 8.25 8.25 0 0 1-8.25 8.25A8.25 8.25 0 0 1 3.75 12 8.25 8.25 0 0 1 12 3.75zm-2.25 4.5v7.5h1.5v-3h1.5l1.5 3h1.5l-1.62-3.243A2.25 2.25 0 0 0 15.75 10.5 2.25 2.25 0 0 0 13.5 8.25zm1.5 1.5h1.5a.75.75 0 0 1 .75.75.75.75 0 0 1-.75.75h-1.5z" />
    </svg>
  );
}
