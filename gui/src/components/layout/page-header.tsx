import { ExternalLinkIcons, RequestFeatureButton } from "./external-links";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div
      data-testid="page-header"
      className="flex items-center justify-between mb-8 pb-4 border-b border-default"
    >
      <div>
        <h1 className="text-2xl font-semibold text-primary-text">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-secondary">{description}</p>
        )}
      </div>
      <div className="flex items-center gap-3">
        {actions && <div className="flex items-center gap-3">{actions}</div>}
        {actions && (
          <span aria-hidden="true" className="h-6 w-px bg-default" />
        )}
        <RequestFeatureButton />
        <span aria-hidden="true" className="h-6 w-px bg-default" />
        <ExternalLinkIcons />
      </div>
    </div>
  );
}
