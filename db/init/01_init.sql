create extension if not exists vector;

create schema if not exists rag;

create table if not exists rag.embeddings (
    id          bigserial primary key,
    source_url  text         not null,
    chunk       text         not null,
    embedding   vector(1536) not null
);
