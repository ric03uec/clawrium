interface IconProps {
  className?: string;
  title?: string;
}

export function ZhipuIcon({ className = "h-4 w-4", title }: IconProps) {
  return (
    <svg
      role="img"
      aria-label={title ?? "Zhipu AI"}
      viewBox="0 0 24 24"
      className={className}
      fill="currentColor"
    >
      <path d="M4 4h16v2.5H8.5L16 9v2.5H4V9h11.5L8 6.5V4zm4 9h12v2.5h-7.5L20 18v2.5H8V18h7.5L8 15.5V13z" />
    </svg>
  );
}
