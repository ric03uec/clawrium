"use client";

import { Modal } from "@/components/ui/modal";

const DISCORD_INVITE = "https://discord.gg/KzPuSxgQ98";
const FEATURE_REQUEST_URL =
  "https://github.com/ric03uec/clawrium/issues/new?template=feature_request.yml";

interface ComingSoonModalProps {
  open: boolean;
  onClose: () => void;
  featureName: string;
  body: string;
  upvoteUrl: string;
}

export function ComingSoonModal({
  open,
  onClose,
  featureName,
  body,
  upvoteUrl,
}: ComingSoonModalProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`${featureName} — coming soon`}
      footer={
        <button
          onClick={onClose}
          className="px-4 h-9 rounded-lg text-sm font-medium text-secondary hover:text-primary hover:bg-panel transition-colors"
        >
          Close
        </button>
      }
    >
      <p className="mb-5">{body}</p>

      <div className="flex flex-col gap-2">
        <ActionLink
          href={upvoteUrl}
          label={`Upvote ${featureName} on GitHub`}
          icon={<ThumbsUpIcon />}
          text="Upvote on GitHub"
          primary
        />
        <ActionLink
          href={DISCORD_INVITE}
          label="Join the discussion on Discord"
          icon={<DiscordIcon />}
          text="Join the discussion on Discord"
        />
        <ActionLink
          href={FEATURE_REQUEST_URL}
          label="Request a different feature"
          icon={<SparkleIcon />}
          text="Request a different feature"
        />
      </div>
    </Modal>
  );
}

function ActionLink({
  href,
  label,
  icon,
  text,
  primary = false,
}: {
  href: string;
  label: string;
  icon: React.ReactNode;
  text: string;
  primary?: boolean;
}) {
  const base =
    "flex items-center justify-between gap-3 px-4 h-11 rounded-lg border text-sm font-medium transition-colors";
  const tone = primary
    ? "border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100"
    : "border-default bg-white text-primary-text hover:bg-panel";
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      aria-label={label}
      className={`${base} ${tone}`}
    >
      <span className="flex items-center gap-2.5">
        <span className="flex items-center justify-center h-5 w-5">{icon}</span>
        {text}
      </span>
      <ExternalArrowIcon />
    </a>
  );
}

function ThumbsUpIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M7 22V11" />
      <path d="M2 13a2 2 0 0 1 2-2h3v11H4a2 2 0 0 1-2-2v-7Z" />
      <path d="M7 11l5-9a2 2 0 0 1 2 2v5h6a2 2 0 0 1 2 2l-2 8a2 2 0 0 1-2 2H7" />
    </svg>
  );
}

function DiscordIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="currentColor"
    >
      <path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z" />
    </svg>
  );
}

function SparkleIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2 2-5z" />
    </svg>
  );
}

function ExternalArrowIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 12 12"
      className="h-3 w-3 text-muted"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 9l6-6M5 3h4v4" />
    </svg>
  );
}
