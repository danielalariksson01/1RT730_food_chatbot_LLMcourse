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

def chat(inputs, history, request: gr.Request):

    #tillåt bara text men om de skickar bild så ska det inte krasha
    text_from_input = inputs.get('text')
    #image_from_input = inputs.get('files')
    
    #behåll
    message = [{"role": "user", "content": text_from_input}] + (history or [])
    
    #behåll
    message_text = "\n".join(f"{m['role']}: {m['content']}" for m in message if isinstance(m.get("content"), str))
    
    #denna ska inte finnas
    r""" if image_from_input:
        file_obj = image_from_input[0]
        file_path = getattr(file_obj, "name", None) or (file_obj if isinstance(file_obj, str) else None)
        if not file_path or not Path(file_path).exists():
            yield "Kunde inte hitta filväg: " + str(file_path)
            return

        uploaded_file = client.files.upload(file=Path(file_path))

        system_instruction = (
            'You are an expert in mushrooms and you have to provide information about the mushroom from the picture attached. Return exactly one JSON object and no additional information. Format: { "common_name": "Inkcap", "genus": "Coprinus", "confidence": 0.5, "visible": ["cap", "hymenium", "stipe"], "color": "orange", "edible": true }'
        )

        result = client.models.generate_content(
            model=default_model,
            contents=[uploaded_file, "\n\n", system_instruction],
        )

        mushroom_json_text = getattr(result, "text", None) or (getattr(result, "output_text", None) if hasattr(result, "output_text") else str(result))
        print("JSON:", mushroom_json_text)
        chats[request.session_hash] = mushroom_json_text """
    
    #denna ska inte finnas
    r""" elif chats[request.session_hash] == None:
        yield "Send a picture of a mushroom"
        return """
     
    #denna ska finnas, ändra system_instruction och lägg till själva RAG systemet   
    #lägga till allergier
    #användaren måste på något sätt i prompten säga hur många recept man vill ha och annars använda standard mått. Men en LLM får prompten som input och sedan ska en annan skriva JSON, för att sedan göra embedding på dem orden, hitta recept och sedan ska en LLM bygga själva recepten men hjälp av produkterna.
    #punish recept som har något med deras allergi i och gör produkter som innehåller ingredienser som de redan har i sitt kök mer attraktiva.
    if text_from_input:
        #gör embedding på message och sedan använd för att göra en vector sökning i databasen och hämta de 5 mest relevanta recepten. Använd sedan dessa recept som kontext i system_instruction.
        json_recipes = client.interactions.create(
            model=default_model,
            system_instruction= """You are the first step in a meal-planning chatbot whose goal is to reduce household food waste. You turn the user's request into a structured plan. Code parses your output with json.loads and uses it to search a recipe database, so the user never sees your output. The input is the conversation as "role: content" lines. The first line is the user's newest message, and the lines after it are earlier turns. Plan for the newest message, and use the earlier turns for things that still apply, such as an allergy mentioned before.

Return a JSON object with three keys:

"recipies": a list with one object per meal, each with a single key "ingredients". The value is a comma-separated string of four to eight ingredient names for one concrete dish, for example "chicken, rice, garlic, onion, soy sauce". Each string is compared with a database of English recipes described by their ingredient names, so write plain English ingredient names in lowercase, without quantities, brands or cooking methods, also when the user writes in another language.

"diet": a list of things the user cannot or will not eat. Code checks each entry as a piece of text inside the recipes' English ingredient names, so write ingredient words in lowercase singular, such as "peanut" or "milk". For a diet that covers a whole category, write the name of the diet and then the common ingredients it rules out: for a vegetarian, "vegetarian", "chicken", "beef", "pork", "bacon", "sausage", "fish", "shrimp". For lactose intolerance, "lactose", "milk", "cream", "butter", "cheese", "yogurt".

"owned_products": a list of food the user already has and wants to use up, as English ingredient names in lowercase singular.

How to plan the meals:
- Make as many meals as the user asks for, and 7 if they give no number.
- When the user describes some meals and not others, follow their wishes for the ones they describe and decide the rest yourself. Plan main meals unless they ask for something else, such as baking or breakfast.
- Give each meal a different main ingredient or style, so the database search returns different recipes.
- Let fresh ingredients that are sold in larger packs than one meal needs (cream, fresh herbs, cabbage, minced meat) appear in two of the meals, so that the pack gets used up.
- Spread the owned products over the meals where they fit, since using them up is the point.
- Never put anything from "diet" in a meal.

Always include all three keys. Use an empty list [] when the user has no restrictions or no owned products, and never put an empty string in a list. Return only the JSON object, with double-quoted keys and strings and no markdown, code fences or other text.

Example of the shape, for a user who asked for two dinners, is allergic to peanuts and has half a cabbage at home:
{"recipies": [{"ingredients": "cabbage, minced beef, onion, rice, crushed tomatoes"}, {"ingredients": "salmon, potato, cabbage, lemon, dill, cream"}], "diet": ["peanut"], "owned_products": ["cabbage"]}""",

            input=[{"type": "text", "text": message_text}],
        )
        
        #hitta ett recept för varje recipe som finns i json filen och gör embedding på dem och använd dessa embeddings för att göra en vector sökning i databasen och hämta de 5 mest relevanta recepten. Använd sedan dessa recept som kontext i system_instruction.
        json_text = json_recipes.output_text.strip()
        recipes = json.loads(json_text)

        diet = [d.lower() for d in recipes.get("diet", [])] 
        owned_products = [p.lower() for p in recipes.get("owned_products", [])]
        
        conn = psycopg2.connect(
            dbname="recipes",
            user="food",
            password="food",
            host="db"
        )
        register_vector(conn)
        cur = conn.cursor()
        
        recipes_chosen = {}
        
        for i, recipe in enumerate(recipes.get("recipies", [])):
            ingredients = recipe.get("ingredients", "")
            embedded_ingredients = client.models.embed_content(
                model="gemini-embedding-001",
                contents=ingredients
            )
            embedded_vector = np.array(embedded_ingredients.embeddings[0].values)
            #gör embedding på ingredienserna och använd dessa embeddings för att göra en vector sökning i databasen och hämta de 5 mest relevanta recepten. Använd sedan dessa recept som kontext i system_instruction.
            #hämta de 5 mest relevanta recepten från databasen
            cur.execute("SELECT title, ingredients FROM recipes ORDER BY embedding <=> %s LIMIT 5;", (embedded_vector,))
            relevant_recipes = cur.fetchall()
            scored_matches = []
            for title, ingredients in relevant_recipes:
                score = 0
                for ingredient in ingredients.lower().split(", "):
                    if any(d in ingredient for d in diet):
                        score -= 1
                    elif any(p in ingredient for p in owned_products):
                        score += 0.2
                scored_matches.append((score, title, ingredients))
            scored_matches.sort(reverse=True)

            
           #i denna delen ska vi sedan lägga in att den väljer utifrån produkter i svenska mataffärer
            ingredients_embeddings = []
          
            result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=scored_matches[0][2]  # Use the ingredients of the top scored match
            )
            ingredients_embeddings.extend(result.embeddings)

            embedded_vector = np.array(ingredients_embeddings[0].values)

            cur.execute("SELECT product_name, quantity, allergens, embedding <=> %s AS distance FROM ingredients ORDER BY distance LIMIT 3;", (embedded_vector,))
            relevant_ingredients = cur.fetchall()

            chosen_recipe = client.interactions.create(
                model=default_model,
                system_instruction="""You are one step in a meal-planning pipeline whose goal is to reduce household food waste. An earlier step has already picked one recipe for the user. Your job is to turn it into a concrete ingredient list with quantities. Your output is parsed by code with json.loads and then passed to another model that writes the final answer, so the user never sees your output directly.

The input contains four fields:
- Recipes: a single recipe as (score, title, ingredients). The ingredients are names only, without quantities. Ignore the score.
- Diet: the user's dietary restrictions and allergies. May be empty.
- Owned Products: food the user already has at home and wants to use up. May be empty.
- Relevant Ingredients: up to three products from Swedish grocery stores, each as (product name, package size, allergens, distance). They come from an automatic similarity search, so some of them may have nothing to do with the recipe.

Write the ingredient list for this recipe, scaled to 4 portions.

Quantities: the recipe has none, so estimate realistic amounts from how the dish is normally cooked. Use metric units (g, kg, ml, dl, l), and tbsp, tsp or a count where that is the natural measure.

Diet: treat this as a hard limit, since it may be an allergy. Never output an ingredient that violates it, including less obvious sources (soy sauce contains wheat, pesto usually contains nuts and cheese). Replace a violating ingredient with an alternative that keeps the dish working, or leave it out if it is minor. Also check the allergens field before using a store product.

Owned products: use them wherever they fit the dish, in place of a similar ingredient, because using up what is already at home is the point. Do not force in a product that does not belong in the dish.

Store products: when a product in Relevant Ingredients really is one of the recipe's ingredients, use its product name and pick an amount that uses the whole package or a simple fraction of it, so that nothing is left over. Ignore products that do not match any ingredient.

Staples: you only see one recipe, but the user is getting several for the same week. Where it does not change the dish, choose common staples (yellow onion, garlic, crushed tomatoes, rice, pasta, cooking oil, milk, eggs) over specialty variants, so that the recipes end up sharing purchases.

Keep the recipe title as given, unless a substitution replaced the main ingredient and the title would be misleading.

Return a single JSON object with double-quoted keys and strings, with no markdown, code fences or text around it:
{"chosen_recipe": "<title>", "ingredients": ["<quantity> <ingredient>", "<quantity> <ingredient>"]}

Each ingredient is one string with the quantity first, for example "400 g crushed tomatoes", "2 tbsp olive oil", "1 yellow onion".""",

                input=[{"type": "text", "text": f"Recipes: {scored_matches[0]}, Diet: {diet}, Owned Products: {owned_products}, Relevant Ingredients: {relevant_ingredients}"}],

            )
            recipes_chosen[i] = json.loads(chosen_recipe.output_text.strip())
           
            #gör per recept och sedan lägg i en lista och sedan ta en annan modell som bara sammanställer detta, men vill egentligen ha en prompt per recept.
            #vad händer om alla recept man får innehåller saker som man är allergisk mot?
        
        conn.close()
        
        #nu ska chatten summera allt
        interaction = client.interactions.create(
            model=default_model,
            system_instruction="""You write the final answer in a meal-planning chatbot whose goal is to reduce household food waste. Earlier steps have already chosen the recipes and worked out their ingredient lists. Your reply is shown directly to the user in a chat window that renders markdown.

The input contains two parts:
- User question: the user's original message, which may mention allergies, dietary restrictions and food they already have at home.
- Chosen recipes: a dictionary of recipes, each with a title (chosen_recipe) and a list of ingredients with quantities. Every recipe is scaled to 4 portions.

Present the recipes as a meal plan, in the order given. Use only these recipes and keep their ingredients and quantities as they are, since they were chosen to share purchases and use up whole packages. Do not add recipes of your own.

For each recipe, write:
- the title as a heading
- the ingredients as a bullet list
- a short description of how to cook it, in three to five sentences. The data has no cooking instructions, so write these from how the dish is normally made, using only the listed ingredients.

After the recipes, write one combined shopping list for the whole plan. Add up ingredients that appear in several recipes into a single line, and leave out anything the user said they already have at home. If the user mentioned food they own, add a line saying which recipes use it.

As a final safety check, compare each recipe with the allergies and dietary restrictions in the user's message. If a recipe still contains something the user cannot eat, leave that recipe out and say in one sentence which one you removed and why, so the user knows the plan is one meal short.

Write in the same language as the user's message, and keep store product names exactly as they are given. Start directly with the plan, without describing how the recipes were chosen, and keep the text around the lists brief.""",
                 input=[{"type": "text", "text": f"User question: {text_from_input}"},
                     {"type": "text", "text": f"Chosen recipes: {recipes_chosen}"}],
            stream=True
        )
        
        #den ska fortfarande göra stream
        full_response=""
        for event in interaction:
            if event.event_type=="step.delta":
                if event.delta.type == "text":
                    full_response += event.delta.text
    
    #else borde inte behövas finnas eftersom de måste ha något i prompten
    r""" else:
        interaction = client.interactions.create(
            model=default_model,
            system_instruction="Summarize information about the mushroom in a written out paragraph. Also add if the mushroom is poisonous, explain whether it could be safe to eat in any state or preperation and desribe the conditions under which it might be edible.",
            input={"type": "text", "text": chats[request.session_hash]},
            stream=True
        )
        full_response=""
        for event in interaction:
            if event.event_type=="step.delta":
                if event.delta.type =="text":
                    full_response += event.delta.text
                    yield full_response
    return """
        
        
demo  = gr.ChatInterface(fn=chat, multimodal=True)

demo.launch()