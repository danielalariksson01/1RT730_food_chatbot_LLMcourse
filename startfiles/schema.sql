CREATE DATABASE recipes;

\c recipes;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS recipes(
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    ingredients TEXT,
    ingredient_amounts TEXT[],
    embedding VECTOR(3072)
);

ALTER TABLE recipes ADD COLUMN IF NOT EXISTS ingredient_amounts TEXT[];

CREATE TABLE IF NOT EXISTS ingredients(
    product_name TEXT NOT NULL,
    quantity TEXT,
    ingredients_text TEXT,
    allergens TEXT,
    embedding VECTOR(3072)
);
