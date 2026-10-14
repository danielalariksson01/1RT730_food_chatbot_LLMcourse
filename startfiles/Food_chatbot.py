import gradio as gr
from collections import defaultdict
from google import genai
import json
import psycopg2
from pgvector.psycopg2 import register_vector
import numpy as np

client = genai.Client()
default_model = "gemini-3.8-flash"

if "demo" in locals() and demo.is_running:
    demo.close()

chats = defaultdict(lambda: None)

#Problem:
#Alla recept har inte ingredienser och allergier, exempelvis om någon skriver gluten
#Hur vet jag hur bra den gissar mängden om databasen inte har det

def embed(text):
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text
    )
    return np.array(result.embeddings[0].values)

def search_products(cur, product):
    embedded_vector = embed(product)
    cur.execute("SELECT product_name, quantity, allergens, embedding <=> %s AS distance FROM ingredients WHERE embedding <=> %s < %s ORDER BY distance LIMIT %s;", (embedded_vector, embedded_vector, 0.3, 10))
    relevant_products= cur.fetchall()
    return [p for p in relevant_products if p[1] is not None] or None


def find_products_per_ingredient(cur, ingredients):
    if not ingredients:
        return {}
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=ingredients
    )
    products = {}
    for ingredient, embedding in zip(ingredients, result.embeddings):
        embedded_vector = np.array(embedding.values)
        cur.execute("SELECT product_name, quantity, allergens, embedding <=> %s AS distance FROM ingredients WHERE embedding <=> %s < %s ORDER BY distance LIMIT %s;", (embedded_vector, embedded_vector, 0.3, 3))
        products[ingredient] = cur.fetchall() or None
    return products

def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)

def chat(inputs, history, request: gr.Request):

    text_from_input = inputs.get('text')
    if text_from_input is None:
        yield "This is a recipe food assistant chatbot"
        return
    if text_from_input.strip() == "":
        yield "This is a recipe food assistant chatbot"
        return
    
    message = [{"role": "user", "content": text_from_input}] + (history or [])

    message_text = "\n".join(f"{m['role']}: {m['content']}" for m in message if isinstance(m.get("content"), str))

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
                system_instruction="""You are the first step in a meal-planning chatbot whose goal is to reduce household food waste. Your output is parsed by code with json.loads. Translate everything the user said to swedish.

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

            wanted_recipies = [r.lower() for r in user_asks.get("specific_recipies") or [] if isinstance(r, str)]
            diet = [d.lower() for d in user_asks.get("diet") or [] if isinstance(d, str)]
            owned_products = [{"product_name": p, "quantity": None} if isinstance(p, str) else p for p in user_asks.get("owned_products") or []]
            owned_products = [p for p in owned_products if isinstance(p, dict) and p.get("product_name")]
            number_of_people = user_asks.get("number_of_people")
            number_of_recipes = user_asks.get("number_of_recipes")
            if not isinstance(number_of_people, int) or number_of_people <1:
                number_of_people=None
            if not isinstance(number_of_recipes, int) or number_of_recipes<1:
                number_of_recipes=None

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

If there is not a specific wanted recipe, put null instead of the recipe name that the user provided.

Return only a JSON object with double-quoted keys and strings, and no markdown, code fences or other text:
{"recipes": [{"wanted_recipe": "lasagne", "ingredients": [{"name": "chicken breast", "package_size": "900 g", "amount_used": "450 g"}, {"name": "rice", "package_size": "1 kg", "amount_used": "300 g"}]}, {"wanted_recipe": null, "ingredients": [{"name": "chicken breast", "package_size": "900 g", "amount_used": "450 g"}, {"name": "rice", "package_size": "1 kg", "amount_used": "300 g"}]}]}""",
                input=[{"type": "text", "text": f"Diet: {diet}, Household products: {owned_products}, Wanted ingredients: {checked_ingredients}, Additional ingredients: {checked_other_ingredients}, Wanted recipes: {wanted_recipies}, Number of people: {number_of_people}, Number of recipes: {number_of_recipes}"}],
            )

            recipes = parse_json(json_recipies.output_text)
            if isinstance(recipes, list):
                recipes = {"recipes": recipes}

            planned_recipes = []

            for recipe in recipes.get("recipes") or []:
                if not isinstance(recipe, dict):
                    continue
                planned_ingredients = [ingredient for ingredient in recipe.get("ingredients") or [] if isinstance(ingredient, dict)]
                specific_recipe = recipe.get("wanted_recipe")
                ingredient_names = ", ".join(ingredient.get("name", "") for ingredient in planned_ingredients)
                if not ingredient_names:
                    continue
                if specific_recipe:
                    embedding = embed(f"{specific_recipe}: {ingredient_names}")
                    cur.execute("SELECT title, ingredients, ingredient_amounts, embedding <=> %s AS distance FROM recipes WHERE embedding <=> %s < %s ORDER BY distance LIMIT 3;", (embedding, embedding, 0.35))
                else:
                    embedding = embed(ingredient_names)
                    cur.execute("SELECT title, ingredients, ingredient_amounts, embedding <=> %s AS distance FROM recipes WHERE embedding <=> %s < %s ORDER BY distance LIMIT 3;", (embedding, embedding, 0.35))
                relevant_recipes = cur.fetchall()
                
                recipies_with_ingredients = []
                for title, ingredients, ingredient_amounts, distance in relevant_recipes:
                    recipe_ingredients = [ingredient for ingredient in ingredients.split(", ") if ingredient]
                    recipies_with_ingredients.append({
                        "title": title,
                        "distance": round(distance, 3),
                        "ingredients": ingredient_amounts or recipe_ingredients,
                        "store_products": find_products_per_ingredient(cur, recipe_ingredients),
                    })

                relevant_ingredients = None
                if not recipies_with_ingredients:
                    relevant_ingredients = find_products_per_ingredient(cur, [ingredient.get("name") for ingredient in planned_ingredients if ingredient.get("name")])

                planned_recipes.append({
                    "wanted_recipe": specific_recipe,
                    "planned_ingredients": planned_ingredients,
                    "candidate_recipes": recipies_with_ingredients or None,
                    "relevant_ingredients": relevant_ingredients,
                })

        finally:
            conn.close()

        interaction = client.interactions.create(
            model=default_model,
            system_instruction="""You are the last step in a meal-planning chatbot whose goal is to reduce household food waste. An earlier step has already planned the protein source and carbohydrate source of each recipe, with quantities. Your job is to choose one recipe from the database for each planned recipe, adapt it, and write the meal plan. Your reply is shown directly to the user in a chat window that renders markdown.

The input contains these parts:
- User question: the user's newest message.
- Diet: the user's dietary restrictions and allergies. May be empty.
- Pantry: food the user already has at home and wants to use up, with quantities when known. May be empty.
- Number of people: how many portions every recipe is for.
- Planned recipes: a list with one entry per recipe in the plan. Each entry has:
  - wanted_recipe: the complete meal the user asked for, or None.
  - planned_ingredients: the ingredients this recipe must contain, each with the package size and the amount the recipe uses (amount_used). Keep these ingredients and amounts as they are, since they were planned so that whole packages get used across the recipes.
  - candidate_recipes: up to five similar recipes from the database, closest first. Each has a title, a distance (lower means more similar to the planned ingredients), an ingredient list, usually with the quantities from the original recipe, for example "450 g uncooked medium shrimp, peeled and deveined", and store_products, where each ingredient of that recipe maps to up to three products from Swedish grocery stores, each as (product name, package size, allergens, distance), or to None when no product was found. The store products come from an automatic similarity search, so some of them may not really be that ingredient. May be None when no recipe was similar enough.
  - relevant_ingredients: only given when there are no candidate recipes. Each planned ingredient maps to store products in the same format as store_products. Otherwise None.

Choosing the recipes: for each planned recipe, go through every candidate recipe and choose the one that fits best. First rule out every candidate where an ingredient that is central to the dish violates the diet, so that it cannot simply be replaced or left out, and every candidate you have already chosen for another planned recipe, so that no recipe appears twice in the plan. Among the rest, prefer the one that fits the planned ingredients and the wanted recipe, and that can use the most pantry products, and use the distance to break ties. If every candidate is ruled out, treat it as if there were no database recipe.

Build each recipe on the chosen database recipe: use its ingredients and its quantities as the starting point, and leave out the parts that do not fit together with the planned ingredients.

Scaling: the database recipe does not say how many portions it makes, so first estimate that from its quantities and the kind of dish (for example, 450 g meat in a main course is usually about 4 portions). Then scale every quantity from that number of portions to the given number of people.

Quantities: keep the quantities from the database recipe after scaling, and only estimate amounts for ingredients that have none or that you add yourself. Convert to metric units (g, kg, ml, dl, l), and use tbsp, tsp or a count where that is the natural measure. Round to amounts that are practical to measure, such as "2 dl" instead of "237 ml". Ingredients without an exact quantity, such as "salt and pepper to taste", may stay that way. If there is no database recipe, estimate all quantities from how the dish is normally cooked for the given number of people.

Diet: treat this as a hard limit, since it may be an allergy. Go through every ingredient of every recipe and check it against the diet, including less obvious sources (soy sauce contains wheat, pesto usually contains nuts and cheese). When an ingredient violates the diet, replace it with an alternative that keeps the dish working, for example lactose-free cream instead of cream, or leave it out if it is minor. Never include an ingredient that violates the diet. Also check the allergens field before using a store product.

Pantry: using up the pantry is the point of the meal plan, so every pantry product must be used in at least one recipe, unless it violates the diet. Use a pantry product in place of a similar ingredient or as an extra ingredient, and leave it out of a recipe only if it would clearly ruin that dish. When the user gave a quantity, never use more than they have across all recipes together.

Store products: for each ingredient, look at its products in store_products of the chosen recipe, or in relevant_ingredients when there is no database recipe. When one of them really is that ingredient, replace the ingredient with that product name and pick an amount that uses the whole package or a simple fraction of it. If one recipe does not use the whole package, use the rest in another recipe, so that nothing is left over. Keep the original ingredient name when none of its products match or when it maps to None.

Staples: where it does not change the dish, choose common staples (yellow onion, garlic, crushed tomatoes, rice, pasta, cooking oil, milk, eggs) over specialty variants, so that the recipes share purchases.

Present the recipes as a meal plan, in the order of the planned recipes. For each recipe, write:
- the title of the chosen database recipe as a heading, exactly as it is, without translating or rewording it, even when you have adjusted the recipe, so that the user can find the original recipe. Only when there is no database recipe, write a short title that describes the dish.
- directly under the heading, when you changed anything apart from scaling to the number of people: a short paragraph that starts with "Adjusted:" (in the user's language) and says what was changed from the original recipe and why, for example ingredients replaced because of the diet, replaced by planned ingredients, or pantry products you added.
- the ingredients as a bullet list, each with the quantity first, for example "400 g crushed tomatoes", "2 tbsp olive oil", "1 yellow onion".
- a short description of how to cook it, in three to five sentences. The data has no cooking instructions, so write these from how the dish is normally made, using only the listed ingredients.

After the recipes, write one combined shopping list for the whole plan. Add up ingredients that appear in several recipes into a single line, and leave out everything in the pantry. If the pantry is not empty, add a line saying which recipes use each pantry product.

Write in the same language as the user's message, and keep store product names exactly as they are given. Start directly with the plan, without describing how the recipes were chosen, and keep the text around the lists brief.""",
            input=[{"type": "text", "text": f"User question: {text_from_input}"},
                   {"type": "text", "text": f"Diet: {diet}"},
                   {"type": "text", "text": f"Pantry: {owned_products}"},
                   {"type": "text", "text": f"Number of people: {number_of_people}"},
                   {"type": "text", "text": f"Planned recipes: {planned_recipes}"}],
            stream=True
        )

        full_response=""
        for event in interaction:
            if event.event_type=="step.delta":
                if event.delta.type == "text":
                    full_response += event.delta.text
                    yield full_response


start_message = "Hi, I will help you plan your recipies and minimize the food waste. Tell me what kind of recipies you want, how many you are, how many recipies in total and if there is something you want to use from home and how much you have."
demo  = gr.ChatInterface(fn=chat, multimodal=True, chatbot=gr.Chatbot(value=[{"role":"assistant", "content":start_message}]))

theme = gr.themes.Soft(primary_hue="orange", secondary_hue="blue", neutral_hue="slate")
demo.launch(theme=theme)
