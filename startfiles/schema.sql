CREATE DATABASE recepies;

\c recepies;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS recipes(
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    ingredients TEXT,
    embedding VECTOR(3072)
)