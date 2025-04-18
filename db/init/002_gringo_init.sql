-- Core tables for the gringo crawler
create schema if not exists gringo;

create table if not exists gringo.pages (
	id           bigserial primary key,
	url          text not null unique,
	title        text,
	content      text not null,
	embedding    vector(1536),
	raw_page_id  bigint,                            -- FK added below
	created_at   timestamptz default current_timestamp,
	updated_at   timestamptz default current_timestamp
);

create table if not exists gringo.affiliate_links (
	id          bigserial primary key,
	url         text not null,
	link_text   text,
	is_active   boolean default true,
	created_at  timestamptz default current_timestamp,
	updated_at  timestamptz default current_timestamp,
	unique(url, link_text)
);

create table if not exists gringo.page_affiliate_links (
	page_id      bigint references gringo.pages(id) on delete cascade,
	affiliate_id bigint references gringo.affiliate_links(id) on delete cascade,
	created_at   timestamptz default current_timestamp,
	primary key (page_id, affiliate_id)
);

-- FK from pages → raw_pages will be added in 003 after raw_pages exists
create index if not exists idx_pages_url  on gringo.pages(url);
create index if not exists idx_aff_links  on gringo.affiliate_links(url);
create index if not exists idx_pal_page   on gringo.page_affiliate_links(page_id);
create index if not exists idx_pal_aff    on gringo.page_affiliate_links(affiliate_id);
