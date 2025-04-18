-- Raw HTML cache (one row per fetched URL)
create table if not exists gringo.raw_pages (
	id         bigserial primary key,
	url        text not null unique,
	html       text not null,
	fetched_at timestamptz default current_timestamp
);

create index if not exists idx_raw_pages_url on gringo.raw_pages(url);

-- Add FK from gringo.pages → raw_pages.id (nullable)
alter table gringo.pages
	add column if not exists raw_page_id bigint references gringo.raw_pages(id) on delete set null;
