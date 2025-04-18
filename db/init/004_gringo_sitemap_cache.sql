create table if not exists gringo.sitemap_cache (
	id          bigserial primary key,
	url         text not null unique,
	fetched_at  timestamp with time zone not null default current_timestamp
);
create index if not exists idx_sitemap_url on gringo.sitemap_cache(url);
