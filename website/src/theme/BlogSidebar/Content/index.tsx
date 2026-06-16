import React, {memo, type ReactNode} from 'react';
import {useThemeConfig} from '@docusaurus/theme-common';
import Heading from '@theme/Heading';
import type {Props} from '@theme/BlogSidebar/Content';
import type {BlogSidebarItem} from '@docusaurus/plugin-content-blog';

const MONTH_FORMATTER = new Intl.DateTimeFormat('en-US', {
  month: 'long',
  year: 'numeric',
});

function groupItemsByMonth(
  items: readonly BlogSidebarItem[],
): [string, BlogSidebarItem[]][] {
  const groups = new Map<string, BlogSidebarItem[]>();
  for (const item of items) {
    const date = new Date(item.date);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(
      2,
      '0',
    )}`;
    const bucket = groups.get(key);
    if (bucket) {
      bucket.push(item);
    } else {
      groups.set(key, [item]);
    }
  }
  return Array.from(groups.entries()).sort(([a], [b]) => (a < b ? 1 : -1));
}

function formatMonthHeading(key: string): string {
  const [year, month] = key.split('-').map(Number);
  return MONTH_FORMATTER.format(new Date(year, month - 1, 1));
}

function BlogSidebarMonthGroup({
  heading,
  headingClassName,
  children,
}: {
  heading: string;
  headingClassName?: string;
  children: ReactNode;
}) {
  return (
    <div role="group">
      <Heading as="h3" className={headingClassName}>
        {heading}
      </Heading>
      {children}
    </div>
  );
}

function BlogSidebarContent({
  items,
  yearGroupHeadingClassName,
  ListComponent,
}: Props): ReactNode {
  const themeConfig = useThemeConfig();
  if (themeConfig.blog.sidebar.groupByYear) {
    const grouped = groupItemsByMonth(items);
    return (
      <>
        {grouped.map(([key, monthItems]) => (
          <BlogSidebarMonthGroup
            key={key}
            heading={formatMonthHeading(key)}
            headingClassName={yearGroupHeadingClassName}>
            <ListComponent items={monthItems} />
          </BlogSidebarMonthGroup>
        ))}
      </>
    );
  }
  return <ListComponent items={items} />;
}

export default memo(BlogSidebarContent);
