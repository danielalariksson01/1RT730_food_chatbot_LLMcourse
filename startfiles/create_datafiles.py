#Read in data
#For each recipie, identify the ingredients and their quantities, and store them in a structured format (e.g., a dictionary or a list of tuples).

#Convert measuremts to a standard unit (e.g., grams or milliliters) to ensure consistency across recipes.


#emedings on the ingredients and quantities can be used to create a knowledge base for the chatbot to reference when answering questions about recipes.

#import kagglehub

# Download latest version

#take out 500 random recipise from recipes_data_matric.csv

import pandas as pd
from google import genai
import os
import psycopg2
from pgvector.psycopg2 import register_vector
import ast
import time
from google.genai import errors

#df = pd.read_csv("C:\\Users\\danie\\VSCODE\\LLM_course\\1RT730_food_chatbot_LLMcourse\\startfiles\\data\\recipes_data_metric.csv")
#df_sample = df.sample(n=500)
#df_sample.to_csv("C:\\Users\\danie\\VSCODE\\LLM_course\\1RT730_food_chatbot_LLMcourse\\startfiles\\data\\first_500_recipes.csv", index=False)

#------------ CREATE TABLE recipes (
recipes = pd.read_csv("/home/jovyan/work/data/first_500_recipes.csv")

recipes["NER"] = recipes["NER"].apply(ast.literal_eval)

client = genai.Client()

#embedd one batch, wait and retry if we hit the rate limit (429)
def embed_batch(batch, max_retries=5):
    for attempt in range(max_retries):
        try:
            result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=batch)
            time.sleep(2.5) #max ~24 batches/min, quota is 3000 embeddings/min
            return result.embeddings
        except errors.ClientError as e:
            if e.code != 429 or attempt == max_retries - 1:
                raise
            print(f"Rate limit hit, waiting 20s (attempt {attempt + 1}/{max_retries})")
            time.sleep(20)
#for loop för att plocka ut NER, gör embedding och skicka in i vectordb
recipes_NER = []
for recipe in recipes.itertuples():
    recipes_NER.append(recipe.title + ": " + ", ".join(recipe.NER))

embeddings=[]
#embedd in batches of 100
for i in range(0,len(recipes_NER),100):
    batch = recipes_NER[i:i+100]
    embeddings.extend(embed_batch(batch))


conn = psycopg2.connect(
    dbname="recipes",
    user="food",
    password="food",
    host="db"
)
register_vector(conn)
cur = conn.cursor()

for i, recipe in enumerate(recipes.itertuples()):
    embedding = embeddings[i].values
    cur.execute("INSERT INTO recipes (title, ingredients, embedding) VALUES (%s, %s, %s)", (recipe.title, ", ".join(recipe.NER), embedding)) 
    
conn.commit()

#----------CREATE TABLE Ingredients 

product_names = pd.read_csv("/home/jovyan/work/data/openfoodfacts_subset_sweden.csv", usecols=["product_name", "quantity", "ingredients_text", "allergens"])

#for loop för att plocka ut product_name kolumnen, gör embedding och skicka in i vectordb
product_list = []
for product in product_names.itertuples():
    product_list.append(product.product_name)

embeddings=[]
#embedd in batches of 100
for i in range(0,len(product_list),100):
    batch = product_list[i:i+100]
    embeddings.extend(embed_batch(batch))


conn = psycopg2.connect(
    dbname="recipes",
    user="food",
    password="food",
    host="db"
)
register_vector(conn)
cur = conn.cursor()

for i, product in enumerate(product_names.itertuples()):
    embedding = embeddings[i].values
    cur.execute("INSERT INTO ingredients (product_name, quantity, ingredients_text, allergens, embedding) VALUES (%s, %s, %s, %s, %s)", (product.product_name, product.quantity, product.ingredients_text, product.allergens, embedding)) 
    
conn.commit()




