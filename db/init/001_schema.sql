-- Enable pgvector and create schemas
create extension if not exists vector;

create schema if not exists gringo;

-- Cache of every <loc> in the sitemap
create table if not exists gringo.sitemap_cache (
	id         bigserial primary key,
	url        text unique not null,
	fetched_at timestamptz not null default current_timestamp
);
create index if not exists idx_sitemap_url on gringo.sitemap_cache(url);

-- Raw HTML for any page we ever fetch
create table if not exists gringo.raw_pages (
	id         bigserial primary key,
	url        text unique not null,
	html       text not null,
	fetched_at timestamptz not null default current_timestamp
);
create index if not exists idx_raw_pages_url on gringo.raw_pages(url);

-- Vector‑searchable document table
create table if not exists gringo.documents (
	id         bigserial primary key,
	url        text unique not null,
	title      text,
	content    text not null,
	embedding  vector(1536) not null,
	raw_page_id bigint references gringo.raw_pages(id) on delete set null,
	created_at timestamptz default current_timestamp,
	updated_at timestamptz default current_timestamp
);
create index if not exists idx_documents_url  on gringo.documents(url);

-- Optional affiliate‑link bookkeeping
create table if not exists gringo.affiliate_links (
	id         bigserial primary key,
	url        text not null,
	link_text  text,
	is_active  boolean default true,
	created_at timestamptz default current_timestamp,
	updated_at timestamptz default current_timestamp,
	unique(url, link_text)
);

create table if not exists gringo.page_affiliate_links (
	page_id      bigint references gringo.documents(id) on delete cascade,
	affiliate_id bigint references gringo.affiliate_links(id) on delete cascade,
	created_at   timestamptz default current_timestamp,
	primary key (page_id, affiliate_id)
);
create index if not exists idx_pal_page on gringo.page_affiliate_links(page_id);
create index if not exists idx_pal_aff  on gringo.page_affiliate_links(affiliate_id);
