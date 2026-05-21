import { GithubIcon } from "@/components/icons/github";
import { DocsIcon } from "@/components/icons/docs";
import { DiscordIcon } from "@/components/icons/discord";

export const EXTERNAL_LINKS = [
  {
    label: "GitHub",
    href: "https://github.com/ric03uec/clawrium",
    Icon: GithubIcon,
  },
  {
    label: "Docs",
    href: "https://ric03uec.github.io/clawrium/",
    Icon: DocsIcon,
  },
  {
    label: "Discord",
    href: "https://discord.gg/KzPuSxgQ98",
    Icon: DiscordIcon,
  },
] as const;

const FEATURE_REQUEST_URL =
  "https://github.com/ric03uec/clawrium/issues/new?template=feature_request.yml";

interface ExternalLinkRowsProps {
  className?: string;
}

export function ExternalLinkRows({ className = "" }: ExternalLinkRowsProps) {
  return (
    <ul className={`space-y-1 ${className}`}>
      {EXTERNAL_LINKS.map(({ label, href, Icon }) => (
        <li key={label}>
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="flex items-center gap-2 px-1 py-1.5 text-sm text-secondary hover:text-primary transition-colors rounded"
          >
            {/* Icon is decorative — visible label provides the link name. */}
            <Icon className="h-4 w-4" />
            <span>{label}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

interface ExternalLinkIconsProps {
  className?: string;
}

export function ExternalLinkIcons({ className = "" }: ExternalLinkIconsProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {EXTERNAL_LINKS.map(({ label, href, Icon }) => (
        <a
          key={label}
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          aria-label={label}
          title={label}
          className="flex items-center justify-center h-9 w-9 rounded-lg text-primary-text hover:text-primary hover:bg-panel transition-colors"
        >
          {/* Icon is decorative — link's aria-label provides the name. */}
          <Icon className="h-[18px] w-[18px]" />
        </a>
      ))}
    </div>
  );
}

export function RequestFeatureButton() {
  return (
    <a
      href={FEATURE_REQUEST_URL}
      target="_blank"
      rel="noreferrer noopener"
      className="flex items-center gap-1.5 px-3 h-9 rounded-lg text-sm text-primary-text hover:text-primary hover:bg-panel transition-colors whitespace-nowrap"
    >
      <GithubIcon className="h-[18px] w-[18px]" />
      <span>Request a feature</span>
    </a>
  );
}
