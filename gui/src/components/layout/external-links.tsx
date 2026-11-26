import type { ReactNode } from "react";
import { DocsIcon } from "@/components/icons/docs";
import { GithubIcon } from "@/components/icons/github";

const DOCUMENTATION_URL = "https://ric03uec.github.io/clawrium/";
const FEATURE_REQUEST_URL =
  "https://github.com/ric03uec/clawrium/issues/new?template=feature_request.yml";

function HeaderExternalLink({ href, icon, children }: { href: string; icon: ReactNode; children: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      aria-label={children}
      className="flex h-9 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-sm text-primary-text transition-colors hover:bg-panel hover:text-primary-foreground"
    >
      {icon}
      <span>{children}</span>
    </a>
  );
}

export function DocumentationButton() {
  return (
    <HeaderExternalLink href={DOCUMENTATION_URL} icon={<DocsIcon className="h-[18px] w-[18px]" />}>
      Documentation
    </HeaderExternalLink>
  );
}

export function RequestFeatureButton() {
  return (
    <HeaderExternalLink href={FEATURE_REQUEST_URL} icon={<GithubIcon className="h-[18px] w-[18px]" />}>
      Request a feature
    </HeaderExternalLink>
  );
}
