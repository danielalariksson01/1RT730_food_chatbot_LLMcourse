import gradio as gr
from collections import defaultdict
from google import genai
from pathlib import Path
import json
import psycopg2
from pgvector.psycopg2 import register_vector
import numpy as np

client = genai.Client()
default_model = "gemini-3.8-flash"

if "demo" in locals() and demo.is_running:
    demo.close()

chats = defaultdict(lambda: None)


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)

def content_to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    return ""

def parse_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count > 0 else None

def embed(text):
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text
    )
    return np.array(result.embeddings[0].values)

def search_products(cur, product):
    relevant_products = find_close_products(cur, product, 10)
    return [p for p in relevant_products if p[1] is not None] or None

def find_close_products(cur, text, limit):
    embedded_vector = embed(text)
    cur.execute("SELECT product_name, quantity, allergens, embedding <=> %s AS distance FROM ingredients WHERE embedding <=> %s < %s ORDER BY distance LIMIT %s;", (embedded_vector, embedded_vector, 0.3, limit))
    return cur.fetchall()

def find_products_per_ingredient(cur, ingredients, limit):
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=ingredients
    )
    products = {}
    for ingredient, embedding in zip(ingredients, result.embeddings):
        embedded_vector = np.array(embedding.values)
        cur.execute("SELECT product_name, quantity, allergens, embedding <=> %s AS distance FROM ingredients WHERE embedding <=> %s < %s ORDER BY distance LIMIT %s;", (embedded_vector, embedded_vector, 0.3, limit))
        products[ingredient] = cur.fetchall() or None
    return products

def chat(inputs, history, request: gr.Request):

    text_from_input = inputs.get('text')

    message = [{"role": "user", "content": text_from_input}] + (history or [])

    message_text = "\n".join(f"{m['role']}: {content_to_text(m.get('content'))}" for m in message if content_to_text(m.get("content")))

    if text_from_input:
        conn = psycopg2.connect(
                    dbname="recipes",
                    user="food",
                    password="food",
                    host="db"
                )
        try:
            register_vector(conn)
            cur = conn.cursor()
            json_user_asks = client.interactions.create(
                model=default_model,
                system_instruction="""You are the first step in a meal-planning chatbot whose goal is to reduce household food waste. Your output is parsed by code with json.loads, so the user never sees it.

The input is the conversation as "role: content" lines. The first line is the user's newest message, and the lines after it are earlier turns. Plan for the newest message, and use the earlier turns for things that still apply, for example when the user answers a question about how many people are eating or how many recipes they want, or mentioned an allergy before.

Identify the following from the conversation:
- specific_recipies: complete meals the user asks for, for example "lasagne". May be empty.
- ingredients: ingredients the user wants in their meals. If the user asks for a complete meal, add its main ingredients here, for example minced beef and pasta for lasagne.
- other_ingredients: protein sources and carbohydrate sources that are not already in ingredients, so that the meal plan becomes a balanced diet. Suggest several different ones (for example chicken, lentils, salmon, potatoes, rice, bulgur) so that there is variety between the recipes, and never suggest anything that conflicts with the user's diet.
- diet: the user's dietary restrictions and allergies.
- owned_products: food the user already has at home, with the quantity if the user mentions it.
- number_of_people: how many people are eating.
- number_of_recipes: how many recipes the user wants.

Use an empty list when the user mentions no specific recipes, ingredients, dietary restrictions or owned products. Use null for number_of_people, number_of_recipes or a quantity that the user does not mention.

Return only a JSON object with double-quoted keys and strings, and no markdown, code fences or other text. Example:
{"specific_recipies": ["lasagne"], "ingredients": ["minced beef", "pasta"], "other_ingredients": ["chicken", "lentils", "potatoes", "rice"], "diet": ["lactose"], "owned_products": [{"product_name": "carrots", "quantity": "500 g"}], "number_of_people": 2, "number_of_recipes": 3}""",
                input=[{"type": "text", "text": message_text}],
            )

            user_asks = parse_json(json_user_asks.output_text)

            wanted_recipies = [r.lower() for r in user_asks.get("specific_recipies") or []]
            diet = [d.lower() for d in user_asks.get("diet") or []]
            owned_products = [p for p in user_asks.get("owned_products") or [] if p.get("product_name")]
            owned_names = [p["product_name"].lower() for p in owned_products]
            number_of_people = parse_count(user_asks.get("number_of_people"))
            number_of_recipes = parse_count(user_asks.get("number_of_recipes"))

            missing = []
            if number_of_people is None:
                missing.append("how many people are eating")
            if number_of_recipes is None:
                missing.append("how many recipes they want")
            if missing:
                question = client.interactions.create(
                    model=default_model,
                    system_instruction="You are a meal-planning chatbot. Before you can plan the meals, you need to know the things listed in the input. Ask the user for them in one short, friendly question, in the same language as the user's message. Write only the question.",
                    input=[{"type": "text", "text": f"User message: {text_from_input}, Missing: {missing}"}],
                )
                yield question.output_text
                return

            checked_ingredients = {product: search_products(cur, product) for product in user_asks.get("ingredients") or []}
            checked_other_ingredients = {product: search_products(cur, product) for product in user_asks.get("other_ingredients") or []}

            json_recipies = client.interactions.create(
                model=default_model,
                system_instruction="""You are the second step in a meal-planning chatbot whose goal is to reduce household food waste. You decide which protein source and carbohydrate source each recipe is built around. Your output is parsed by code with json.loads, so the user never sees it.

The input contains:
- Diet: the user's dietary restrictions and allergies. Treat this as a hard limit, since it may be an allergy.
- Household products: food the user already has in the pantry, with quantities when known. Using them up is the point, so every household product must be used in at least one recipe, unless it violates the diet. When a household product is a protein or carbohydrate source, plan a recipe around it before you use a store product for the same role.
- Wanted ingredients and additional ingredients: each ingredient maps to a list of products from Swedish grocery stores as (product name, package size, allergens, distance), or to None. Wanted ingredients may be empty when the user did not ask for any, and then you build every recipe from the additional ingredients. The products come from an automatic similarity search, so ignore products that are not really that ingredient. If the value is None or no product matches, guess the package size the ingredient is usually sold in, in Swedish grocery stores.
- Wanted recipes: complete meals the user asked for. May be empty.
- Number of people and number of recipes.

Plan exactly the given number of recipes. Each recipe has exactly one protein source and one carbohydrate source. The exception is a wanted recipe: build one recipe for each wanted recipe, and include its main ingredients even if they are not protein or carbohydrates. Prefer the wanted ingredients, and use the additional ingredients to make the plan a balanced diet, for example so that not every recipe uses the same protein. Never use an ingredient that violates the diet, and check the allergens of the store products.

For each ingredient, give the package size it is sold in and how much of it the recipe uses for the given number of people. If one recipe does not use the whole package, use the rest in another recipe, so that nothing is wasted.

Return only a JSON object with double-quoted keys and strings, and no markdown, code fences or other text:
{"recipes": [{"ingredients": [{"name": "chicken breast", "package_size": "900 g", "amount_used": "450 g"}, {"name": "rice", "package_size": "1 kg", "amount_used": "300 g"}]}]}""",
                input=[{"type": "text", "text": f"Diet: {diet}, Household products: {owned_products}, Wanted ingredients: {checked_ingredients}, Additional ingredients: {checked_other_ingredients}, Wanted recipes: {wanted_recipies}, Number of people: {number_of_people}, Number of recipes: {number_of_recipes}"}],
            )

            recipes = parse_json(json_recipies.output_text)

            recipes_chosen = {}

            for i, recipe in enumerate(recipes.get("recipes") or []):
                planned_ingredients = recipe.get("ingredients") or []
                ingredient_names = ", ".join(ingredient.get("name", "") for ingredient in planned_ingredients)
                if not ingredient_names:
                    continue
                cur.execute("SELECT title, ingredients, ingredient_amounts FROM recipes ORDER BY embedding <=> %s LIMIT 5;", (embed(ingredient_names),))
                relevant_recipes = cur.fetchall()
                scored_matches = []
                for title, ingredients, ingredient_amounts in relevant_recipes:
                    score = 0
                    for ingredient in ingredients.lower().split(", "):
                        if any(d in ingredient for d in diet):
                            score -= 1
                        elif any(p in ingredient for p in owned_names):
                            score += 0.2
                    scored_matches.append((score, title, ingredients, ingredient_amounts))
                scored_matches.sort(key=lambda match: match[0], reverse=True)
                best_match = scored_matches[0] if scored_matches else None
                database_recipe = {"title": best_match[1], "ingredients": best_match[3] or best_match[2]} if best_match else None

                recipe_ingredients = best_match[2].split(", ") if best_match else [ingredient.get("name", "") for ingredient in planned_ingredients]
                relevant_ingredients = find_products_per_ingredient(cur, [ingredient for ingredient in recipe_ingredients if ingredient], 3)

                chosen_recipe = client.interactions.create(
                    model=default_model,
                    system_instruction="""You are one step in a meal-planning pipeline whose goal is to reduce household food waste. An earlier step has already planned the protein source and carbohydrate source of this recipe, with quantities. Your job is to adapt a recipe from the database into a complete recipe with an ingredient list with quantities. Your output is parsed by code with json.loads and then passed to another model that writes the final answer, so the user never sees your output directly.

The input contains:
- Planned ingredients: the ingredients this recipe must contain, each with the package size and the amount the recipe uses (amount_used). Keep these ingredients and amounts as they are, since they were planned so that whole packages get used across the recipes.
- Recipe from database: a similar recipe with its title and its ingredient list, usually with the quantities from the original recipe, for example "450 g uncooked medium shrimp, peeled and deveined". May be None.
- Diet: the user's dietary restrictions and allergies. May be empty.
- Owned Products: food the user already has at home and wants to use up, with quantities when known. May be empty.
- Relevant Ingredients: each ingredient of the database recipe maps to up to three products from Swedish grocery stores, each as (product name, package size, allergens, distance), or to None when no product was found. They come from an automatic similarity search, so some of them may not really be that ingredient.
- Number of people: how many portions the recipe is for.

Build the recipe on the database recipe: use its ingredients and its quantities as the starting point, and leave out the parts that do not fit together with the planned ingredients.

Scaling: the database recipe does not say how many portions it makes, so first estimate that from its quantities and the kind of dish (for example, 450 g meat in a main course is usually about 4 portions). Then scale every quantity from that number of portions to the given number of people.

Quantities: keep the quantities from the database recipe after scaling, and only estimate amounts for ingredients that have none or that you add yourself. Convert to metric units (g, kg, ml, dl, l), and use tbsp, tsp or a count where that is the natural measure. Round to amounts that are practical to measure, such as "2 dl" instead of "237 ml". Ingredients without an exact quantity, such as "salt and pepper to taste", may stay that way. If there is no database recipe, estimate all quantities from how the dish is normally cooked for the given number of people.

Diet: treat this as a hard limit, since it may be an allergy. Go through every ingredient of the database recipe and check it against the diet, including less obvious sources (soy sauce contains wheat, pesto usually contains nuts and cheese). When an ingredient violates the diet, adjust the recipe: replace it with an alternative that keeps the dish working, for example lactose-free cream instead of cream, or leave it out if it is minor. Never output an ingredient that violates the diet. Also check the allergens field before using a store product.

Owned products: the user's pantry must be used up, since that is the point of the meal plan. Use every owned product that can work in this dish, in place of a similar ingredient or as an extra ingredient, and leave one out only if it would clearly ruin the dish. When the user gave a quantity, never use more than they have.

Store products: for each ingredient, look at its products in Relevant Ingredients. When one of them really is that ingredient, replace the ingredient with that product name and pick an amount that uses the whole package or a simple fraction of it, so that nothing is left over. Keep the original ingredient name when none of its products match or when it maps to None.

Staples: you only see one recipe, but the user is getting several for the same week. Where it does not change the dish, choose common staples (yellow onion, garlic, crushed tomatoes, rice, pasta, cooking oil, milk, eggs) over specialty variants, so that the recipes end up sharing purchases.

Title: keep the title of the recipe from the database exactly as it is, without translating or rewording it, even when you have adjusted the recipe, so that the user can find the original recipe. Only when there is no database recipe, write a short title that describes the dish.

Changes: list every adjustment you made to the database recipe, apart from scaling to the number of people. That includes ingredients you replaced or left out because of the diet, ingredients replaced by planned ingredients, owned products you added, and other ingredients you left out or added. Write each change as one short sentence that also says why, for example "Replaced the cream with lactose-free cream because of the lactose intolerance." Use an empty list when you made no adjustments.

Return a single JSON object with double-quoted keys and strings, with no markdown, code fences or text around it:
{"chosen_recipe": "<title>", "changes": ["<change>", "<change>"], "ingredients": ["<quantity> <ingredient>", "<quantity> <ingredient>"]}

Each ingredient is one string with the quantity first, for example "400 g crushed tomatoes", "2 tbsp olive oil", "1 yellow onion".""",

                    input=[{"type": "text", "text": f"Planned ingredients: {planned_ingredients}, Recipe from database: {database_recipe}, Diet: {diet}, Owned Products: {owned_products}, Relevant Ingredients: {relevant_ingredients}, Number of people: {number_of_people}"}],

                )
                recipes_chosen[i] = parse_json(chosen_recipe.output_text)

        finally:
            conn.close()

        interaction = client.interactions.create(
            model=default_model,
            system_instruction="""You write the final answer in a meal-planning chatbot whose goal is to reduce household food waste. Earlier steps have already chosen the recipes and worked out their ingredient lists. Your reply is shown directly to the user in a chat window that renders markdown.

The input contains these parts:
- User question: the user's newest message.
- Diet: the user's dietary restrictions and allergies. May be empty.
- Pantry: food the user already has at home, with quantities when known. May be empty.
- Number of people: how many portions every recipe is scaled to.
- Chosen recipes: a dictionary of recipes, each with a title (chosen_recipe), a list of changes made to the original recipe, and a list of ingredients with quantities.

Present the recipes as a meal plan, in the order given. Use only these recipes and keep their ingredients and quantities as they are, since they were chosen to share purchases and use up whole packages. Do not add recipes of your own.

For each recipe, write:
- the title as a heading, exactly as given, without translating or rewording it, so that the user can find the original recipe
- directly under the heading, when the recipe has changes: a short paragraph that starts with "Adjusted:" (in the user's language) and explains what was changed from the original recipe and why
- the ingredients as a bullet list
- a short description of how to cook it, in three to five sentences. The data has no cooking instructions, so write these from how the dish is normally made, using only the listed ingredients.

After the recipes, write one combined shopping list for the whole plan. Add up ingredients that appear in several recipes into a single line, and leave out everything in the pantry. If the pantry is not empty, add a line saying which recipes use each pantry product.

As a final safety check, compare each recipe with the diet. If a recipe still contains something the user cannot eat, adjust it: replace the ingredient with a safe alternative in the ingredient list and the cooking description, and add the change to the "Adjusted:" paragraph of that recipe. Only if the dish cannot work without the ingredient, leave the recipe out and say in one sentence which one you removed and why.

Write in the same language as the user's message, and keep store product names exactly as they are given. Start directly with the plan, without describing how the recipes were chosen, and keep the text around the lists brief.""",
                 input=[{"type": "text", "text": f"User question: {text_from_input}"},
                     {"type": "text", "text": f"Diet: {diet}"},
                     {"type": "text", "text": f"Pantry: {owned_products}"},
                     {"type": "text", "text": f"Number of people: {number_of_people}"},
                     {"type": "text", "text": f"Chosen recipes: {recipes_chosen}"}],
            stream=True
        )

        full_response=""
        for event in interaction:
            if event.event_type=="step.delta":
                if event.delta.type == "text":
                    full_response += event.delta.text
                    yield full_response


demo  = gr.ChatInterface(fn=chat, multimodal=True)

demo.launch()
