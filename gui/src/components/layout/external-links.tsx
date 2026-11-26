import { GithubIcon } from "@/components/icons/github";

const FEATURE_REQUEST_URL =
  "https://github.com/ric03uec/clawrium/issues/new?template=feature_request.yml";

export function RequestFeatureButton() {
  return (
    <a
      href={FEATURE_REQUEST_URL}
      target="_blank"
      rel="noreferrer noopener"
      className="flex items-center gap-1.5 px-3 h-9 rounded-lg text-sm text-primary-text hover:text-primary-foreground hover:bg-panel transition-colors whitespace-nowrap"
    >
      <GithubIcon className="h-[18px] w-[18px]" />
      <span>Request a feature</span>
    </a>
  );
}
