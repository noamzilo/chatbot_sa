-- Enable pgvector and create schemas
create extension if not exists vector;

create schema if not exists gringo;

-- Cache of raw HTML fetched from sitemap URLs
create table if not exists gringo.raw_pages (
	id         bigserial primary key,
	url        text unique not null,
	html       text not null,
	fetched_at timestamptz not null default current_timestamp
);
create index if not exists idx_raw_pages_url on gringo.raw_pages(url);

-- Vector‑searchable document table (one entry per parsed+embedded page)
create table if not exists gringo.documents (
	id          bigserial primary key,
	url         text unique not null,
	title       text,
	content     text not null,
	embedding   vector(1536) not null,
	raw_page_id bigint references gringo.raw_pages(id) on delete set null,
	created_at  timestamptz default current_timestamp,
	updated_at  timestamptz default current_timestamp
);
create index if not exists idx_documents_url on gringo.documents(url);
