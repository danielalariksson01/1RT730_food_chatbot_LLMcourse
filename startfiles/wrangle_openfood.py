import csv
from pathlib import Path

import pandas as pd
#drop all rows where countries_en is not Sweden 

df = pd.read_csv(
    r"C:\Users\danie\VSCODE\LLM_course\1RT730_food_chatbot_LLMcourse\startfiles\data\en.openfoodfacts.org.products.csv",
    sep="\t",
    usecols=["product_name", "generic_name", "quantity", "ingredients_text", "ingredients_tags", "allergens", "countries_en"],
    low_memory=False,
    on_bad_lines="skip",
) 
print(df.shape)

df = df[df["countries_en"] == "Sweden"]
df = df.dropna(subset=["product_name"])

df.to_csv(
    r"C:\Users\danie\VSCODE\LLM_course\1RT730_food_chatbot_LLMcourse\startfiles\data\openfoodfacts_subset_sweden.csv",
    index=False,
    encoding="utf-8",
)

r""" print(df.shape)

path = r"C:\Users\danie\VSCODE\LLM_course\1RT730_food_chatbot_LLMcourse\startfiles\data\openfoodfacts_subset.csv"
df = pd.read_csv(path, low_memory=False)
print("Före:", df.shape)

df = df.replace(r"^\s*$", pd.NA, regex=True)

df_full = df.dropna()
print("Efter:", df_full.shape)

df_full.to_csv(
    r"C:\Users\danie\VSCODE\LLM_course\1RT730_food_chatbot_LLMcourse\startfiles\data\openfoodfacts_complete.csv",
    index=False,
    encoding="utf-8",
) """


