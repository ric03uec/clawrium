// Full eject (not a @theme-original wrapper): upstream BlogListPage instantiates
// BlogLayout internally without exposing the `toc` slot, so the only way to mount
// a right rail on the listing is to re-implement the page body. Re-sync this file
// from @docusaurus/theme-classic on every minor bump.
import React, {type ReactNode} from 'react';
import clsx from 'clsx';

import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {
  PageMetadata,
  HtmlClassNameProvider,
  ThemeClassNames,
} from '@docusaurus/theme-common';
import BlogLayout from '@theme/BlogLayout';
import BlogListPaginator from '@theme/BlogListPaginator';
import SearchMetadata from '@theme/SearchMetadata';
import type {Props} from '@theme/BlogListPage';
import BlogPostItems from '@theme/BlogPostItems';
import BlogListPageStructuredData from '@theme/BlogListPage/StructuredData';
import BlogRightRail from '@site/src/components/BlogRightRail';

function BlogListPageMetadata(props: Props): ReactNode {
  const {metadata} = props;
  const {
    siteConfig: {title: siteTitle},
  } = useDocusaurusContext();
  const {blogDescription, blogTitle, permalink} = metadata;
  const isBlogOnlyMode = permalink === '/';
  const title = isBlogOnlyMode ? siteTitle : blogTitle;
  return (
    <>
      <PageMetadata title={title} description={blogDescription} />
      <SearchMetadata tag="blog_posts_list" />
    </>
  );
}

function BlogListPageContent(props: Props): ReactNode {
  const {metadata, items, sidebar} = props;
  return (
    <BlogLayout sidebar={sidebar} toc={<BlogRightRail />}>
      <BlogPostItems items={items} />
      <BlogListPaginator metadata={metadata} />
    </BlogLayout>
  );
}

export default function BlogListPage(props: Props): ReactNode {
  return (
    <HtmlClassNameProvider
      className={clsx(
        ThemeClassNames.wrapper.blogPages,
        ThemeClassNames.page.blogListPage,
      )}>
      <BlogListPageMetadata {...props} />
      <BlogListPageStructuredData {...props} />
      <BlogListPageContent {...props} />
    </HtmlClassNameProvider>
  );
}
