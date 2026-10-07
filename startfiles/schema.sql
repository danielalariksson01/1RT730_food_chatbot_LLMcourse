CREATE DATABASE recipes;

\c recipes;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS recipes(
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    ingredients TEXT,
    embedding VECTOR(3072)
);

CREATE TABLE IF NOT EXISTS ingredients(
    product_name TEXT NOT NULL,
    quantity TEXT,
    ingredients_text TEXT,
    allergens TEXT,
    embedding VECTOR(3072)
);
