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

#df = pd.read_csv("C:\\Users\\danie\\VSCODE\\LLM_course\\1RT730_food_chatbot_LLMcourse\\startfiles\\data\\recipes_data_metric.csv")
#df_sample = df.sample(n=500)
#df_sample.to_csv("C:\\Users\\danie\\VSCODE\\LLM_course\\1RT730_food_chatbot_LLMcourse\\startfiles\\data\\first_500_recipes.csv", index=False)

recepies = pd.read_csv("/home/jovyan/work/data/first_500_recipes.csv").head(10)

recepies["NER"] = recepies["NER"].apply(ast.literal_eval)

client = genai.Client()
#for loop för att plocka ut NER, gör embedding och skicka in i vectordb
recepies_NER = []
for recepie in recepies.itertuples():
    recepies_NER.append(recepie.title + ", ".join(recepie.NER))

embeddings=[]
#embedd in batches of 100
for i in range(0,len(recepies_NER),100):
    batch = recepies_NER[i:i+100]
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=batch)
    embeddings.extend(result.embeddings)


conn = psycopg2.connect(
    dbname="recepies",
    user="food",
    password="food",
    host="db"
)
register_vector(conn)
cur = conn.cursor()

for i, recipe in enumerate(recepies.itertuples()):
    embedding = embeddings[i].values
    cur.execute("INSERT INTO recipes (title, ingredients, embedding) VALUES (%s, %s, %s)", (recipe.title, ", ".join(recipe.NER), embedding)) 
    
conn.commit()



