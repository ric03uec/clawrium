interface IconProps {
  className?: string;
  title?: string;
}

export function IntelIcon({ className = "h-3.5 w-3.5", title }: IconProps) {
  return (
    <svg
      role="img"
      aria-label={title ?? "Intel"}
      viewBox="0 0 24 24"
      className={className}
      fill="currentColor"
    >
      <path d="M20.49 7.116v9.768H22V7.116zM2 8.404V20h1.55v-9.91zm15.34-1.288c-.5 0-.902.402-.902.902s.402.902.902.902.902-.402.902-.902-.401-.902-.902-.902zM5.05 10.16v6.724h1.51v-5.292c0-.78.36-1.26 1.155-1.26.94 0 1.32.66 1.32 1.46v5.092h1.51v-5.46c0-1.5-.8-2.46-2.34-2.46-.74 0-1.5.32-1.92.92v-.724zm10.36 0v6.724h1.51v-6.724zm-4.5-1.62v6.7c0 1.36.74 1.92 2.07 1.92.46 0 .9-.08 1.18-.16v-1.36c-.16.04-.4.06-.62.06-.66 0-.94-.26-.94-.94v-2.7h1.56v-1.32h-1.56V8.541z" />
    </svg>
  );
}
