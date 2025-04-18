-- Create schema for gringo crawler
create schema if not exists gringo;

-- Table for storing page content with vector embeddings
create table if not exists gringo.pages (
    id          bigserial primary key,
    url         text not null unique,
    title       text,
    content     text not null,
    embedding   vector(1536),
    created_at  timestamp with time zone default current_timestamp,
    updated_at  timestamp with time zone default current_timestamp
);

-- Table for storing affiliate links
create table if not exists gringo.affiliate_links (
    id          bigserial primary key,
    url         text not null,
    link_text   text,
    is_active   boolean default true,
    created_at  timestamp with time zone default current_timestamp,
    updated_at  timestamp with time zone default current_timestamp,
    unique(url, link_text)
);

-- Junction table to link pages with their affiliate links
create table if not exists gringo.page_affiliate_links (
    page_id         bigint references gringo.pages(id) on delete cascade,
    affiliate_id    bigint references gringo.affiliate_links(id) on delete cascade,
    created_at      timestamp with time zone default current_timestamp,
    primary key (page_id, affiliate_id)
);

-- Create indexes for better performance
create index if not exists idx_pages_url on gringo.pages(url);
create index if not exists idx_affiliate_links_url on gringo.affiliate_links(url);
create index if not exists idx_page_affiliate_links_page_id on gringo.page_affiliate_links(page_id);
create index if not exists idx_page_affiliate_links_affiliate_id on gringo.page_affiliate_links(affiliate_id); 